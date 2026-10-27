<template>
<div class="fc" data-testid="fc-root">
  <!-- HERO: what this page is, and the network a new frame would join (read live). -->
  <header class="fc-hero">
    <div class="fc-wrap fc-hero-grid">
      <div class="fc-hero-copy">
        <div class="fc-chip"><span class="fc-chip-dot" aria-hidden="true" />{{ t('frameCommanderView.hero.chip', 'Sovereign frame · review-only') }}</div>
        <h1 class="fc-h1">{{ t('frameCommanderView.hero.h1a', 'Frame ') }}<span class="fc-h1-accent">{{ t('frameCommanderView.hero.h1Accent', 'Commander') }}</span></h1>
        <p class="fc-lead">{{ t('frameCommanderView.hero.lead', 'A frame is a digital nation. This is where you propose one.') }}</p>
        <p class="fc-sub">{{ t('frameCommanderView.hero.sub', 'Your own registry, treasury, ledger and trust domain, run for you and federated with the network when you choose. Describe it below; a person reviews every request.') }}</p>
        <div class="fc-hero-actions">
          <button type="button" class="fc-btn fc-btn--primary" data-testid="fc-start" @click="openForm">
            <Icon name="mdi:rocket-launch" class="fc-btn-icon" />
            {{ hasDraft ? t('frameCommanderView.hero.resume', 'Continue your request') : t('frameCommanderView.hero.start', 'Request a frame') }}
          </button>
          <button type="button" class="fc-btn fc-btn--ghost" @click="scrollToId('fc-journey')">
            {{ t('frameCommanderView.hero.how', 'How it works') }}
          </button>
        </div>
      </div>

      <aside class="fc-card fc-live" data-testid="fc-network" :aria-label="t('frameCommanderView.live.eyebrow', 'The network today')">
        <div class="fc-live-head">
          <span class="fc-eyebrow">{{ t('frameCommanderView.live.eyebrow', 'The network today') }}</span>
          <span class="fc-live-badge"><span class="fc-live-dot" aria-hidden="true" />{{ t('frameCommanderView.live.badge', 'Live') }}</span>
        </div>
        <template v-if="networkState === 'ready'">
          <p class="fc-live-count">{{ framesText }}</p>
          <ul class="fc-live-list">
            <li v-for="p in partners" :key="p.name" class="fc-live-row">
              <span class="fc-live-mark" aria-hidden="true" />
              <span class="fc-live-name">{{ p.name }}</span>
              <span v-if="p.self" class="fc-pill">{{ t('frameCommanderView.live.here', 'You are here') }}</span>
              <span class="fc-live-host">{{ hostOf(p.url) }}</span>
            </li>
          </ul>
          <p v-if="otherRegistries" class="fc-live-foot">{{ othersText }}</p>
        </template>
        <p v-else-if="networkState === 'loading'" class="fc-muted">{{ t('frameCommanderView.live.loading', 'Reading the network…') }}</p>
        <p v-else class="fc-muted">{{ t('frameCommanderView.live.unavailable', 'The list of frames is unavailable right now. The form still works.') }}</p>
      </aside>
    </div>
  </header>

  <!-- WHAT A FRAME IS -->
  <section class="fc-sec" aria-labelledby="fc-what-title">
    <div class="fc-wrap">
      <div class="fc-sec-head">
        <span class="fc-eyebrow">{{ t('frameCommanderView.what.eyebrow', 'What you get') }}</span>
        <h2 id="fc-what-title" class="fc-h2">{{ t('frameCommanderView.what.title', 'A whole registry of your own') }}</h2>
        <p class="fc-sec-lead">{{ t('frameCommanderView.what.lead', 'A cloud operator borrows its frame’s currency, ledger and identity. A frame owns all of them.') }}</p>
      </div>
      <div class="fc-pillars">
        <article
          v-for="(p, i) in pillars"
          :key="p.id"
          class="fc-card fc-pillar"
          :class="{ 'fc-pillar--wide': p.wide }"
          :style="{ '--i': i }"
        >
          <Icon :name="p.icon" class="fc-pillar-icon" />
          <span class="fc-pillar-tag">{{ p.tag }}</span>
          <h3 class="fc-pillar-title">{{ p.title }}</h3>
          <p class="fc-pillar-desc">{{ p.desc }}</p>
        </article>
      </div>
    </div>
  </section>

  <!-- HOW IT GOES -->
  <section id="fc-journey" class="fc-sec" aria-labelledby="fc-journey-title">
    <div class="fc-wrap">
      <div class="fc-sec-head">
        <span class="fc-eyebrow">{{ t('frameCommanderView.journey.eyebrow', 'How it goes') }}</span>
        <h2 id="fc-journey-title" class="fc-h2">{{ t('frameCommanderView.journey.title', 'From this form to a running frame') }}</h2>
        <p class="fc-sec-lead">{{ t('frameCommanderView.journey.lead', 'Nothing after the first step starts until a person has said yes.') }}</p>
      </div>
      <ol class="fc-journey">
        <li v-for="(s, i) in journey" :key="s.id" class="fc-journey-step">
          <span class="fc-journey-num" aria-hidden="true">{{ i + 1 }}</span>
          <div class="fc-journey-copy">
            <h3 class="fc-journey-title">{{ s.title }}</h3>
            <p class="fc-journey-desc">{{ s.desc }}</p>
          </div>
        </li>
      </ol>
    </div>
  </section>

  <!-- THE REQUEST -->
  <section id="fc-form" class="fc-sec fc-sec--form" aria-labelledby="fc-form-title">
    <div class="fc-wrap">
      <div class="fc-sec-head">
        <span class="fc-eyebrow">{{ t('frameCommanderView.wizard.eyebrow', 'Request a frame') }}</span>
        <h2 id="fc-form-title" class="fc-h2">{{ t('frameCommanderView.wizard.title', 'Tell us about your frame') }}</h2>
        <p class="fc-sec-lead">{{ t('frameCommanderView.wizard.lead', 'Six short steps. Fields with a star are required; everything else can be settled during review.') }}</p>
      </div>

      <div v-if="result" ref="successRef" class="fc-card fc-success" data-testid="fc-success" role="status" tabindex="-1">
        <div class="fc-success-badge" aria-hidden="true"><Icon name="mdi:check-decagram" /></div>
        <h3 class="fc-success-title">{{ t('frameCommanderView.success.title', 'Your request is in') }}</h3>
        <p class="fc-success-lead">{{ t('frameCommanderView.success.lead', 'A person reads every frame request. Expect an answer within about seven business days.') }}</p>
        <div v-if="result.request_id" class="fc-success-id">
          <span class="fc-success-id-label">{{ t('frameCommanderView.success.requestId', 'Request id') }}</span>
          <code data-testid="fc-request-id">{{ result.request_id }}</code>
          <button type="button" class="fc-btn fc-btn--small" @click="copyId">
            <Icon :name="copied ? 'mdi:check' : 'mdi:content-copy'" class="fc-btn-icon" />
            {{ copied ? t('frameCommanderView.success.copied', 'Copied') : t('frameCommanderView.success.copy', 'Copy') }}
          </button>
        </div>
        <ul class="fc-success-list">
          <li v-if="result.account_created"><Icon name="mdi:account-check" class="fc-li-icon" />{{ tp('frameCommanderView.success.account', 'A developer account was created for {email}.', { email: result.email }) }}</li>
          <li v-if="result.magic_link_sent"><Icon name="mdi:email-fast" class="fc-li-icon" />{{ tp('frameCommanderView.success.magicLink', 'A sign-in link is on its way to {email}.', { email: result.email }) }}</li>
          <li><Icon name="mdi:email-outline" class="fc-li-icon" />{{ tp('frameCommanderView.success.reply', 'We answer at {email}, and may ask a question or two first.', { email: result.email }) }}</li>
        </ul>
        <router-link v-if="frameKitEnabled" to="/frame-kit" class="fc-btn fc-btn--primary fc-success-follow" data-testid="fc-follow">
          <Icon name="mdi:package" class="fc-btn-icon" />
          {{ t('frameCommanderView.success.follow', 'Follow your request on your frame page') }}
        </router-link>
        <button type="button" class="fc-btn fc-btn--ghost" data-testid="fc-another" @click="startAnother">
          {{ t('frameCommanderView.success.another', 'Start another request') }}
        </button>
      </div>

      <div v-else class="fc-wizard">
        <nav ref="stepsRef" class="fc-steps" :aria-label="t('frameCommanderView.wizard.stepsLabel', 'Request steps')">
          <ol class="fc-steps-list">
            <li v-for="(s, i) in STEPS" :key="s" class="fc-steps-item">
              <button
                type="button"
                class="fc-step"
                :class="stepClass(i)"
                :aria-current="i === step ? 'step' : undefined"
                :disabled="i > furthest"
                :data-testid="'fc-step-' + s"
                :aria-label="stepLabels[s]"
                @click="goTo(i)"
              >
                <span class="fc-step-num" aria-hidden="true">
                  <Icon v-if="stepDone(i)" name="mdi:check" />
                  <Icon v-else-if="stepFlagged(i)" name="mdi:alert" />
                  <template v-else>{{ i + 1 }}</template>
                </span>
                <span class="fc-step-label">{{ stepLabels[s] }}</span>
              </button>
            </li>
          </ol>
          <div class="fc-steps-track" aria-hidden="true"><span class="fc-steps-fill" :style="{ width: progressPct + '%' }" /></div>
        </nav>

        <div ref="gridRef" class="fc-wizard-grid">
          <form ref="panelRef" class="fc-card fc-panel" novalidate :data-testid="'fc-panel-' + current" @submit.prevent="onPrimary">
            <div v-if="restored" class="fc-notice" data-testid="fc-draft-notice">
              <Icon name="mdi:history" class="fc-notice-icon" />
              <span>{{ t('frameCommanderView.wizard.restored', 'We restored the request you started on this device.') }}</span>
              <button type="button" class="fc-link" data-testid="fc-start-fresh" @click="discardDraft">{{ t('frameCommanderView.wizard.startFresh', 'Start fresh') }}</button>
            </div>

            <div class="fc-panel-head">
              <span class="fc-panel-count">{{ tp('frameCommanderView.wizard.stepOf', 'Step {n} of {total}', { n: step + 1, total: STEPS.length }) }}</span>
              <h3 ref="panelTitle" class="fc-panel-title" tabindex="-1">{{ stepTitles[current].title }}</h3>
              <p class="fc-panel-lead">{{ stepTitles[current].lead }}</p>
            </div>

            <!-- 1 CONTACT -->
            <div v-if="current === 'contact'" class="fc-fields">
              <FcField :label="t('frameCommanderView.contact.organization', 'Organization')" required :error="err('organization')" wide>
                <input v-model="draft.organization" class="fc-input" data-testid="fc-f-organization" autocomplete="organization" :maxlength="LIMITS.organization" :placeholder="t('frameCommanderView.contact.organizationPh', 'Harbor Systems GmbH')" :aria-invalid="bad('organization')" @blur="touch('organization')" />
              </FcField>
              <FcField :label="t('frameCommanderView.contact.name', 'Your name')" required :error="err('contact_name')">
                <input v-model="draft.contact_name" class="fc-input" data-testid="fc-f-contact_name" autocomplete="name" :maxlength="LIMITS.contact_name" :aria-invalid="bad('contact_name')" @blur="touch('contact_name')" />
              </FcField>
              <FcField :label="t('frameCommanderView.contact.email', 'Email')" required :error="err('email')" :hint="t('frameCommanderView.contact.emailHint', 'We answer here. It is never published.')">
                <input v-model="draft.email" type="email" class="fc-input" data-testid="fc-f-email" autocomplete="email" inputmode="email" :maxlength="LIMITS.email" :placeholder="t('frameCommanderView.contact.emailPh', 'you@org.example')" :aria-invalid="bad('email')" @blur="touch('email')" />
              </FcField>
              <label class="fc-check fc-fields-wide">
                <input v-model="draft.create_account" type="checkbox" class="fc-check-input" data-testid="fc-f-create_account" />
                <span class="fc-check-box" aria-hidden="true"><Icon name="mdi:check" /></span>
                <span class="fc-check-copy">
                  <span class="fc-check-title">{{ t('frameCommanderView.contact.account', 'Also create a developer account for me on this network') }}</span>
                  <span class="fc-check-sub">{{ t('frameCommanderView.contact.accountSub', 'A sign-in link arrives by email. It does not approve the request.') }}</span>
                </span>
              </label>
            </div>

            <!-- 2 FRAME -->
            <div v-else-if="current === 'frame'" class="fc-fields">
              <FcField as="div" :label="t('frameCommanderView.frame.hosting', 'Where it runs')" wide>
                <FcChoices :model-value="draft.hosting" @update:model-value="choose('hosting', $event)" :options="hostingOptions" :label="t('frameCommanderView.frame.hosting', 'Where it runs')" testid="fc-hosting" :columns="2" />
              </FcField>
              <div class="fc-field-stack">
                <FcField :label="t('frameCommanderView.frame.name', 'Frame name')" required :error="err('frame_name')" :hint="t('frameCommanderView.frame.nameHint', 'Lowercase letters, digits and hyphens, 3 to 31 of them. It cannot change after stand-up.')">
                  <span class="fc-affix">
                    <input :value="draft.frame_name" class="fc-input fc-input--mono" data-testid="fc-f-frame_name" autocapitalize="off" autocomplete="off" spellcheck="false" maxlength="31" :placeholder="t('frameCommanderView.frame.namePh', 'harbor')" :aria-invalid="bad('frame_name')" @input="onFrameName" @blur="touch('frame_name')" />
                    <span v-if="draft.hosting === 'theprotocol'" class="fc-affix-tail">.{{ FRAME_DOMAIN }}</span>
                  </span>
                </FcField>
                <button v-if="nameSuggestion" type="button" class="fc-suggest" data-testid="fc-suggest-name" @click="draft.frame_name = nameSuggestion">
                  <Icon name="mdi:creation" class="fc-btn-icon" />{{ tp('frameCommanderView.frame.suggest', 'Use {name}', { name: nameSuggestion }) }}
                </button>
              </div>
              <FcField :label="t('frameCommanderView.frame.displayName', 'Display name')" required :error="err('display_name')" :counter="{ n: draft.display_name.length, max: LIMITS.display_name }" :hint="t('frameCommanderView.frame.displayNameHint', 'The name people read on your registry card.')">
                <input v-model="draft.display_name" class="fc-input" data-testid="fc-f-display_name" :maxlength="LIMITS.display_name" :placeholder="t('frameCommanderView.frame.displayNamePh', 'Harbor')" :aria-invalid="bad('display_name')" @blur="touch('display_name')" />
              </FcField>
              <FcField v-if="draft.hosting === 'self'" :label="t('frameCommanderView.frame.hostname', 'Hostname')" required :error="err('hostname')" :hint="t('frameCommanderView.frame.hostnameHint', 'Where your console will answer, such as frame.example.org.')" wide>
                <input v-model="draft.hostname" class="fc-input fc-input--mono" data-testid="fc-f-hostname" autocapitalize="off" autocomplete="off" spellcheck="false" :maxlength="LIMITS.hostname" placeholder="frame.example.org" :aria-invalid="bad('hostname')" @blur="touch('hostname')" />
              </FcField>
              <FcField :label="t('frameCommanderView.frame.description', 'Description')" :optional-text="optionalText" :error="err('description')" :counter="{ n: draft.description.length, max: LIMITS.description }" wide>
                <textarea v-model="draft.description" class="fc-input fc-textarea" rows="3" data-testid="fc-f-description" :maxlength="LIMITS.description" :placeholder="t('frameCommanderView.frame.descriptionPh', 'What this frame is for, in a sentence or two.')" @blur="touch('description')" />
              </FcField>
              <FcField as="div" :label="t('frameCommanderView.frame.theme', 'Colour')" :hint="t('frameCommanderView.frame.themeHint', 'The colour of your console and of your mark.')" wide>
                <FcChoices :model-value="draft.theme" @update:model-value="choose('theme', $event)" :options="themeOptions" :label="t('frameCommanderView.frame.theme', 'Colour')" testid="fc-theme" :columns="2" compact />
              </FcField>
              <div class="fc-addresses fc-fields-wide" data-testid="fc-addresses">
                <div class="fc-addresses-head"><Icon name="mdi:web" class="fc-btn-icon" />{{ t('frameCommanderView.frame.addresses', 'Where it will answer') }}</div>
                <dl v-if="addresses" class="fc-addresses-list">
                  <div><dt>{{ t('frameCommanderView.frame.console', 'Console') }}</dt><dd>{{ addresses.console }}</dd></div>
                  <div v-if="addresses.ledger"><dt>{{ t('frameCommanderView.frame.ledger', 'Ledger') }}</dt><dd>{{ addresses.ledger }}</dd></div>
                  <div><dt>{{ t('frameCommanderView.frame.trustDomain', 'Trust domain') }}</dt><dd>{{ addresses.trustDomain }}</dd></div>
                  <div><dt>{{ t('frameCommanderView.frame.identity', 'Workload identity') }}</dt><dd>{{ addresses.spiffe }}</dd></div>
                  <div><dt>{{ t('frameCommanderView.frame.federation', 'Federation') }}</dt><dd>{{ addresses.federation }}</dd></div>
                </dl>
                <p v-else class="fc-muted">{{ t('frameCommanderView.frame.addressesPending', 'The addresses appear as soon as the name is valid.') }}</p>
              </div>
            </div>

            <!-- 3 CURRENCY -->
            <div v-else-if="current === 'currency'" class="fc-fields">
              <FcField :label="t('frameCommanderView.currency.name', 'Currency name')" required :error="err('currency_name')" :counter="{ n: draft.currency_name.length, max: LIMITS.currency_name }">
                <input v-model="draft.currency_name" class="fc-input" data-testid="fc-f-currency_name" :maxlength="LIMITS.currency_name" :placeholder="t('frameCommanderView.currency.namePh', 'Harbor Credit')" :aria-invalid="bad('currency_name')" @blur="touch('currency_name')" />
              </FcField>
              <div class="fc-field-stack">
                <FcField :label="t('frameCommanderView.currency.ticker', 'Ticker')" required :error="err('ticker')" :hint="t('frameCommanderView.currency.tickerHint', '2 to 6 capital letters, such as ECU.')">
                  <input :value="draft.ticker" class="fc-input fc-input--mono fc-input--ticker" data-testid="fc-f-ticker" autocapitalize="characters" autocomplete="off" spellcheck="false" maxlength="6" placeholder="HBC" :aria-invalid="bad('ticker')" @input="onTicker" @blur="touch('ticker')" />
                </FcField>
                <button v-if="tickerSuggestion" type="button" class="fc-suggest" data-testid="fc-suggest-ticker" @click="draft.ticker = tickerSuggestion">
                  <Icon name="mdi:creation" class="fc-btn-icon" />{{ tp('frameCommanderView.currency.suggest', 'Use {ticker}', { ticker: tickerSuggestion }) }}
                </button>
              </div>
              <FcField :label="t('frameCommanderView.currency.mint', 'Genesis issuance')" required :error="err('mint')" :hint="t('frameCommanderView.currency.mintHint', 'Issued once into your treasury at stand-up, at most 1,000,000,000.')">
                <input v-model="draft.mint" class="fc-input fc-input--mono" inputmode="numeric" data-testid="fc-f-mint" :aria-invalid="bad('mint')" @blur="touch('mint')" />
              </FcField>
              <FcField :label="t('frameCommanderView.currency.grant', 'Genesis grant')" :optional-text="optionalText" :error="err('genesis_grant')" :hint="t('frameCommanderView.currency.grantHint', 'What the first agent of each developer receives from the treasury.')">
                <input v-model="draft.genesis_grant" class="fc-input fc-input--mono" inputmode="numeric" data-testid="fc-f-genesis_grant" :aria-invalid="bad('genesis_grant')" @blur="touch('genesis_grant')" />
              </FcField>
              <div class="fc-stats fc-fields-wide">
                <div class="fc-stat">
                  <span class="fc-stat-value">{{ fmt(mintNumber, true) }}</span>
                  <span class="fc-stat-label">{{ t('frameCommanderView.currency.statMint', 'in the treasury at birth') }}</span>
                </div>
                <div class="fc-stat">
                  <span class="fc-stat-value">{{ fmt(grantsCovered) }}</span>
                  <span class="fc-stat-label">{{ t('frameCommanderView.currency.statGrants', 'first-agent grants the issuance covers') }}</span>
                </div>
                <div class="fc-stat">
                  <span class="fc-stat-value">{{ fmt(bond, true) }}</span>
                  <span class="fc-stat-label">{{ t('frameCommanderView.currency.statBond', 'bond an agent posts to sell services, at the default policy') }}</span>
                </div>
              </div>
            </div>

            <!-- 4 PLACE -->
            <div v-else-if="current === 'place'" class="fc-fields">
              <FcField :label="t('frameCommanderView.place.location', 'City and country')" required :error="err('location')" :counter="{ n: draft.location.length, max: LIMITS.location }" :hint="t('frameCommanderView.place.locationHint', 'A city, never a street address. It is published on your card.')" wide>
                <input v-model="draft.location" class="fc-input" data-testid="fc-f-location" autocomplete="address-level2" :maxlength="LIMITS.location" :placeholder="t('frameCommanderView.place.locationPh', 'Brussels, Belgium')" :aria-invalid="bad('location')" @blur="touch('location')" />
              </FcField>
              <div class="fc-fields-wide">
                <FcMapPicker
                  :lat="draft.lat"
                  :lng="draft.lng"
                  :hint="t('frameCommanderView.place.mapHint', 'Click the map where your frame stands, or type the coordinates.')"
                  :label="t('frameCommanderView.place.mapLabel', 'Map. Click to place your frame; the arrow keys move the pin.')"
                  @pick="onPick"
                />
              </div>
              <FcField :label="t('frameCommanderView.place.lat', 'Latitude')" required :error="err('lat')">
                <input v-model="draft.lat" class="fc-input fc-input--mono" inputmode="decimal" data-testid="fc-f-lat" placeholder="50.85" :aria-invalid="bad('lat')" @blur="touch('lat')" />
              </FcField>
              <FcField :label="t('frameCommanderView.place.lng', 'Longitude')" required :error="err('lng')">
                <input v-model="draft.lng" class="fc-input fc-input--mono" inputmode="decimal" data-testid="fc-f-lng" placeholder="4.35" :aria-invalid="bad('lng')" @blur="touch('lng')" />
              </FcField>
              <FcField :label="t('frameCommanderView.place.website', 'Website')" :optional-text="optionalText" :error="err('website')" wide>
                <input v-model="draft.website" type="url" class="fc-input" inputmode="url" data-testid="fc-f-website" :maxlength="LIMITS.website" placeholder="https://" :aria-invalid="bad('website')" @blur="touch('website')" />
              </FcField>
              <FcField as="div" :label="t('frameCommanderView.place.tags', 'Tags')" :optional-text="optionalText" :error="err('tags')" :counter="{ n: draft.tags.length, max: LIMITS.tags }" :hint="tp('frameCommanderView.place.tagsHint', 'Enter or a comma adds a tag, up to {count}.', { count: LIMITS.tags })" wide>
                <div class="fc-tags">
                  <span v-for="(tag, i) in draft.tags" :key="tag" class="fc-tag">
                    {{ tag }}
                    <button type="button" class="fc-tag-x" :aria-label="tp('frameCommanderView.place.removeTag', 'Remove {tag}', { tag })" @click="removeTag(i)"><Icon name="mdi:close" /></button>
                  </span>
                  <input
                    v-model="tagInput"
                    class="fc-tags-input"
                    data-testid="fc-f-tags"
                    :maxlength="LIMITS.tag"
                    :disabled="draft.tags.length >= LIMITS.tags"
                    :placeholder="draft.tags.length ? '' : t('frameCommanderView.place.tagsPh', 'logistics, research')"
                    :aria-label="t('frameCommanderView.place.tags', 'Tags')"
                    @keydown="onTagKey"
                    @blur="addTag"
                  />
                </div>
              </FcField>
            </div>

            <!-- 5 NETWORK AND SETTINGS -->
            <div v-else-if="current === 'network'" class="fc-fields">
              <FcField as="div" :label="t('frameCommanderView.network.intent', 'How your frame meets the others')" :hint="t('frameCommanderView.network.licenceNote', 'Federating needs a network license. A frame without one still runs standalone, with its own cloud operators. Licenses are free for now.')" wide>
                <FcChoices :model-value="draft.intent" @update:model-value="choose('intent', $event)" :options="intentOptions" :label="t('frameCommanderView.network.intent', 'How your frame meets the others')" testid="fc-intent" :columns="3" />
              </FcField>
              <FcField v-if="draft.intent === 'federate_later'" as="div" :label="t('frameCommanderView.network.licence', 'Who runs this frame')" :optional-text="optionalText" :hint="t('frameCommanderView.network.licenceHint', 'Decides the network license the frame is issued. Private, educational, research and non-profit frames: free, with no end date. Enterprise and government: free for the first year.')" wide>
                <FcChoices :model-value="draft.licence_category" @update:model-value="choose('licence_category', $event)" :options="licenceOptions" :label="t('frameCommanderView.network.licence', 'Who runs this frame')" testid="fc-licence" :columns="3" />
              </FcField>
              <FcField v-if="draft.intent === 'federate_later'" as="div" :label="t('frameCommanderView.network.partners', 'Frames to federate with')" :optional-text="optionalText" :error="err('partners')" :hint="t('frameCommanderView.network.partnersHint', 'After stand-up, the frames you pick receive an invitation. Both sides approve it.')" wide>
                <p v-if="networkState === 'loading'" class="fc-muted">{{ t('frameCommanderView.live.loading', 'Reading the network…') }}</p>
                <p v-else-if="networkState === 'failed'" class="fc-muted">{{ t('frameCommanderView.network.partnersFailed', 'The list of frames could not be read. Name them in the notes instead.') }}</p>
                <p v-else-if="!partners.length" class="fc-muted">{{ t('frameCommanderView.network.partnersEmpty', 'No frames are listed on this network yet.') }}</p>
                <div v-else class="fc-partners">
                  <button
                    v-for="p in partners"
                    :key="p.name"
                    type="button"
                    class="fc-partner"
                    :class="{ 'is-on': draft.partners.includes(p.name) }"
                    :aria-pressed="draft.partners.includes(p.name) ? 'true' : 'false'"
                    :data-testid="'fc-partner-' + p.name"
                    @click="togglePartner(p.name)"
                  >
                    <span class="fc-partner-check" aria-hidden="true"><Icon name="mdi:check" /></span>
                    <span class="fc-partner-copy">
                      <span class="fc-partner-name">{{ p.name }}<span v-if="p.self" class="fc-pill">{{ t('frameCommanderView.live.here', 'You are here') }}</span></span>
                      <span class="fc-partner-host">{{ hostOf(p.url) }}</span>
                    </span>
                  </button>
                </div>
              </FcField>
              <FcField as="div" :label="t('frameCommanderView.network.operators', 'Cloud operators')" :error="err('operators')" :hint="t('frameCommanderView.network.operatorsHint', 'Operators run under your frame, on its currency and ledger. More can follow later.')">
                <div class="fc-stepper">
                  <button type="button" class="fc-stepper-btn" :disabled="draft.operators <= 0" :aria-label="t('frameCommanderView.network.fewer', 'One operator fewer')" data-testid="fc-operators-minus" @click="bumpOperators(-1)"><Icon name="mdi:chevron-left" /></button>
                  <output class="fc-stepper-value" data-testid="fc-f-operators" aria-live="polite">{{ draft.operators }}</output>
                  <button type="button" class="fc-stepper-btn" :disabled="draft.operators >= LIMITS.operators" :aria-label="t('frameCommanderView.network.more', 'One operator more')" data-testid="fc-operators-plus" @click="bumpOperators(1)"><Icon name="mdi:chevron-right" /></button>
                </div>
              </FcField>
              <FcField as="div" :label="t('frameCommanderView.network.posture', 'Stage')">
                <FcChoices :model-value="draft.posture" @update:model-value="choose('posture', $event)" :options="postureOptions" :label="t('frameCommanderView.network.posture', 'Stage')" testid="fc-posture" :columns="2" compact />
              </FcField>
              <div class="fc-advanced fc-fields-wide" :class="{ 'is-open': advancedOpen }">
                <button type="button" class="fc-advanced-head" :aria-expanded="advancedOpen ? 'true' : 'false'" data-testid="fc-advanced" @click="advancedOpen = !advancedOpen">
                  <Icon name="mdi:tune" class="fc-advanced-icon" />
                  <span class="fc-advanced-copy">
                    <span class="fc-advanced-title">{{ t('frameCommanderView.network.advanced', 'Advanced settings') }}</span>
                    <span class="fc-advanced-lead">{{ t('frameCommanderView.network.advancedLead', 'Every feature a frame can run, preset to the default we would choose. Change only what you want different.') }}</span>
                  </span>
                  <span v-if="changedCount" class="fc-pill">{{ changedCount }}</span>
                  <Icon name="mdi:chevron-down" class="fc-advanced-chevron" />
                </button>
                <div v-if="advancedOpen" class="fc-advanced-body">
                  <FcSwitchBoard :features="draft.features" @change="onSwitch" @reset="resetSwitches" />
                </div>
              </div>
              <ul v-if="warnings.length" class="fc-warnings fc-fields-wide" data-testid="fc-warnings">
                <li v-for="w in warnings" :key="w.key"><Icon name="mdi:alert" class="fc-li-icon" />{{ tp(w.key, w.fallback, w.params || {}) }}</li>
              </ul>
            </div>

            <!-- 6 REVIEW -->
            <div v-else class="fc-fields">
              <div class="fc-summary fc-fields-wide" data-testid="fc-summary">
                <section v-for="block in summary" :key="block.step" class="fc-summary-block">
                  <header class="fc-summary-head">
                    <h4 class="fc-summary-title">{{ block.title }}</h4>
                    <button type="button" class="fc-link" :data-testid="'fc-edit-' + block.step" @click="goTo(STEPS.indexOf(block.step))">
                      <Icon name="mdi:pencil-outline" class="fc-btn-icon" />{{ t('frameCommanderView.review.edit', 'Edit') }}
                    </button>
                  </header>
                  <dl class="fc-summary-list">
                    <div v-for="row in block.rows" :key="row.label" class="fc-summary-row">
                      <dt>{{ row.label }}</dt>
                      <dd :class="{ 'is-mono': row.mono, 'is-missing': row.missing }">{{ row.value }}</dd>
                    </div>
                  </dl>
                </section>
              </div>
              <FcField :label="t('frameCommanderView.review.why', 'Why do you want a frame?')" required :error="err('use_case')" :counter="{ n: draft.use_case.trim().length, max: LIMITS.use_case }" :hint="t('frameCommanderView.review.whyHint', 'What will run on it, and who will use it. Specific answers are reviewed faster.')" wide>
                <textarea v-model="draft.use_case" class="fc-input fc-textarea" rows="5" data-testid="fc-f-use_case" :maxlength="LIMITS.use_case" :aria-invalid="bad('use_case')" @blur="touch('use_case')" />
              </FcField>
              <FcField :label="t('frameCommanderView.review.notes', 'Anything else')" :optional-text="optionalText" :error="err('notes')" :counter="{ n: draft.notes.length, max: LIMITS.notes }" wide>
                <textarea v-model="draft.notes" class="fc-input fc-textarea" rows="3" data-testid="fc-f-notes" :maxlength="LIMITS.notes" :placeholder="t('frameCommanderView.review.notesPh', 'Timeline, constraints, the organizations you work with.')" @blur="touch('notes')" />
              </FcField>
              <ul v-if="warnings.length" class="fc-warnings fc-fields-wide">
                <li v-for="w in warnings" :key="w.key"><Icon name="mdi:alert" class="fc-li-icon" />{{ tp(w.key, w.fallback, w.params || {}) }}</li>
              </ul>
              <label class="fc-accept fc-fields-wide" data-testid="fc-accept-terms">
                <input v-model="draft.accept_terms" type="checkbox" data-testid="fc-f-accept_terms" />
                <span>{{ t('frameCommanderView.wizard.acceptTerms', 'I accept the Terms of Service and the Federation Operator Terms') }}
                  (<a href="#/legal/terms" target="_blank" rel="noopener noreferrer">Terms</a>, <a href="#/legal/operators" target="_blank" rel="noopener noreferrer">Operator Terms</a>)</span>
              </label>
              <details class="fc-json fc-fields-wide">
                <summary class="fc-json-summary">{{ t('frameCommanderView.review.json', 'The request exactly as it will be sent') }}</summary>
                <pre class="fc-json-body" data-testid="fc-json">{{ payloadJson }}</pre>
              </details>
            </div>

            <p v-if="submitError" class="fc-submit-error" role="alert" data-testid="fc-submit-error">
              <Icon name="mdi:alert-circle" class="fc-li-icon" />{{ submitError }}
            </p>

            <div class="fc-actions">
              <button v-if="step > 0" type="button" class="fc-btn fc-btn--ghost" data-testid="fc-back" @click="back">
                <Icon name="mdi:chevron-left" class="fc-btn-icon" />{{ t('frameCommanderView.wizard.back', 'Back') }}
              </button>
              <span class="fc-draft-state" aria-live="polite">
                <template v-if="savedAt">
                  <Icon name="mdi:content-save-check" class="fc-btn-icon" />
                  <span>{{ t('frameCommanderView.wizard.saved', 'Draft saved on this device') }}</span>
                  <button type="button" class="fc-link" data-testid="fc-discard" @click="discardDraft">{{ t('frameCommanderView.wizard.discard', 'Discard') }}</button>
                </template>
              </span>
              <button v-if="current !== 'review'" type="submit" class="fc-btn fc-btn--primary" data-testid="fc-next">
                {{ t('frameCommanderView.wizard.next', 'Continue') }}<Icon name="mdi:chevron-right" class="fc-btn-icon" />
              </button>
              <button v-else type="submit" class="fc-btn fc-btn--primary" :disabled="submitting" data-testid="fc-submit">
                <Icon :name="submitting ? 'mdi:loading' : 'mdi:send'" class="fc-btn-icon" :class="{ 'fc-spin': submitting }" />
                {{ submitting ? t('frameCommanderView.wizard.sending', 'Sending…') : t('frameCommanderView.wizard.send', 'Send request') }}
              </button>
            </div>
          </form>

          <aside ref="asideRef" class="fc-aside">
            <FcCardPreview :draft="draft" :addresses="addresses" :changed-count="changedCount" />
            <p class="fc-aside-note">
              <Icon name="mdi:information-outline" class="fc-btn-icon" />
              {{ t('frameCommanderView.wizard.previewNote', 'This is what your frame will publish about itself. The frame is created only after the request is approved.') }}
            </p>
          </aside>
        </div>
      </div>
    </div>
  </section>

  <!-- QUESTIONS -->
  <section class="fc-sec" aria-labelledby="fc-faq-title">
    <div class="fc-wrap fc-faq-wrap">
      <div class="fc-sec-head">
        <span class="fc-eyebrow">{{ t('frameCommanderView.faq.eyebrow', 'Questions') }}</span>
        <h2 id="fc-faq-title" class="fc-h2">{{ t('frameCommanderView.faq.title', 'Before you send') }}</h2>
      </div>
      <div class="fc-faq">
        <details v-for="(q, i) in faq" :key="i" class="fc-card fc-faq-item" :open="i === 0">
          <summary class="fc-faq-q">{{ q.q }}<Icon name="mdi:chevron-down" class="fc-faq-chevron" /></summary>
          <p class="fc-faq-a">{{ q.a }}</p>
        </details>
      </div>
      <p class="fc-footer">
        {{ t('frameCommanderView.footer.question', 'A question this page does not answer?') }}
        <a href="mailto:commander@theprotocol.cloud">commander@theprotocol.cloud</a>
      </p>
    </div>
  </section>
</div>
</template>

<script setup lang="ts">
/**
 * FrameCommander: the public request for a frame (§FRAMEFORM rebuild, his word 2026-09-13: "the frame-commander form
 * is not correct anymore needs complete rework and design upgrade ... in form still old legacy frames to choose to
 * federate with etc no advanced settings").
 *
 * The page says what a frame is and how a request becomes one, then walks six steps with a live preview of the
 * registry card. Every rule, derived address, partner list and the payload live in services/frameRequestForm.ts
 * (unit-tested); this file renders them. The partner frames come from the live network (GET /federation/registries
 * and /federation/info), never from a hardcoded list. The draft is kept in this browser only, and nothing reaches the
 * registry before Send, which POSTs /operators/request-frame.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import FcCardPreview from '@/components/frameCommander/FcCardPreview.vue'
import FcChoices from '@/components/frameCommander/FcChoices.vue'
import FcField from '@/components/frameCommander/FcField.vue'
import FcMapPicker from '@/components/frameCommander/FcMapPicker.vue'
import FcSwitchBoard from '@/components/frameCommander/FcSwitchBoard.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { apiClient } from '@/services/api/client'
import { FRAME_FEATURE_SWITCHES } from '@/services/api/frameRequests'
import { appLocale } from '@/services/appLocale'
import {
  DRAFT_STORAGE_KEY,
  FIRST_YEAR_CATEGORIES,
  FRAME_DOMAIN,
  LICENCE_CATEGORIES,
  LIMITS,
  STEPS,
  STEP_FIELDS,
  type DraftField,
  type FrameRequestDraft,
  type NetworkRegistry,
  type StepId,
  blankDraft,
  buildRequestPayload,
  changedFeatures,
  defaultFeatures,
  draftWarnings,
  firstStepWithIssues,
  frameAddresses,
  isPristine,
  networkNames,
  partnerOptions,
  restoreDraft,
  serializeDraft,
  setFeature,
  stepIssues,
  suggestFrameName,
  suggestTicker,
  validateDraft,
  wholeNumber,
} from '@/services/frameRequestForm'

const { t, tp } = useI18n()
// §HELLOFRAME: the success panel points at the applicant's frame page when this frame offers it (FRAME_KIT_ENABLED)
const { frameKitEnabled } = useRegistryConfig()

// ── State ─────────────────────────────────────────────────────────────────────────────────────────────────
const draft = reactive<FrameRequestDraft>(blankDraft())
const step = ref(0)
const furthest = ref(0)
const touched = reactive<Partial<Record<DraftField, boolean>>>({})
const attempted = ref<boolean[]>(STEPS.map(() => false))
const restored = ref(false)
const savedAt = ref<number | null>(null)
const advancedOpen = ref(false)
const tagInput = ref('')
const submitting = ref(false)
const submitError = ref('')
const serverIssues = ref<Partial<Record<DraftField, string>>>({})
const result = ref<{ request_id: string | null; account_created: boolean; magic_link_sent: boolean; email: string } | null>(null)
const copied = ref(false)

const panelRef = ref<HTMLFormElement | null>(null)
const panelTitle = ref<HTMLElement | null>(null)
const stepsRef = ref<HTMLElement | null>(null)
const successRef = ref<HTMLElement | null>(null)
const gridRef = ref<HTMLElement | null>(null)
const asideRef = ref<HTMLElement | null>(null)

const registries = ref<NetworkRegistry[]>([])
const selfName = ref<string | null>(null)
const networkState = ref<'loading' | 'ready' | 'failed'>('loading')

// ── Derived ───────────────────────────────────────────────────────────────────────────────────────────────
const current = computed<StepId>(() => STEPS[step.value])
const selfUrl = typeof window === 'undefined' ? '' : window.location.origin
const partners = computed(() =>
  partnerOptions(registries.value, selfName.value ? { name: selfName.value, url: selfUrl } : null))
const otherRegistries = computed(() =>
  registries.value.filter(r => r.peer_type !== 'frame' && (r.registry_name || '').trim()).length)
const issues = computed(() => validateDraft(draft, networkNames(registries.value, selfName.value)))
const addresses = computed(() => frameAddresses(draft))
const warnings = computed(() => draftWarnings(draft, { kitOffered: frameKitEnabled.value }))
const changedCount = computed(() => Object.keys(changedFeatures(draft.features)).length)
const payloadJson = computed(() => JSON.stringify(buildRequestPayload(draft), null, 2))
const hasDraft = computed(() => !isPristine(draft))
const progressPct = computed(() => (step.value / (STEPS.length - 1)) * 100)
const optionalText = computed(() => t('frameCommanderView.wizard.optional', 'optional'))
const nameSuggestion = computed(() => (draft.frame_name.trim() ? '' : suggestFrameName(draft.organization)))
const tickerSuggestion = computed(() => (draft.ticker.trim() ? '' : suggestTicker(draft.currency_name || draft.display_name)))
const mintNumber = computed(() => wholeNumber(draft.mint))
const grantNumber = computed(() => wholeNumber(draft.genesis_grant))
const grantsCovered = computed(() =>
  (mintNumber.value && grantNumber.value ? Math.floor(mintNumber.value / grantNumber.value) : null))
// The reputation bond an agent posts before it sells services is a quarter of the genesis grant (the default policy).
const bond = computed(() => (grantNumber.value === null ? null : grantNumber.value / 4))

function fmt(n: number | null, withTicker = false): string {
  if (n === null || !Number.isFinite(n)) return '···'
  const text = new Intl.NumberFormat(appLocale(), { maximumFractionDigits: 2 }).format(n)
  return withTicker && draft.ticker ? `${text} ${draft.ticker}` : text
}

function hostOf(url: string): string {
  if (!url) return ''
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

// ── Words ─────────────────────────────────────────────────────────────────────────────────────────────────
const stepLabels = computed<Record<StepId, string>>(() => ({
  contact: t('frameCommanderView.steps.contact', 'Contact'),
  frame: t('frameCommanderView.steps.frame', 'Frame'),
  currency: t('frameCommanderView.steps.currency', 'Currency'),
  place: t('frameCommanderView.steps.place', 'Place'),
  network: t('frameCommanderView.steps.network', 'Network'),
  review: t('frameCommanderView.steps.review', 'Review'),
}))

const stepTitles = computed<Record<StepId, { title: string; lead: string }>>(() => ({
  contact: {
    title: t('frameCommanderView.contact.title', 'Who is asking'),
    lead: t('frameCommanderView.contact.lead', 'The person we write back to, and the organization behind the frame.'),
  },
  frame: {
    title: t('frameCommanderView.frame.title', 'Your frame'),
    lead: t('frameCommanderView.frame.lead', 'Where it runs, what it is called and how it looks. The name cannot change after stand-up.'),
  },
  currency: {
    title: t('frameCommanderView.currency.title', 'Your currency'),
    lead: t('frameCommanderView.currency.lead', 'Every frame issues its own unit once, at birth. The treasury holds it and funds new agents.'),
  },
  place: {
    title: t('frameCommanderView.place.title', 'Where it stands'),
    lead: t('frameCommanderView.place.lead', 'Your registry card carries a place, so the frame shows on the network’s globe.'),
  },
  network: {
    title: t('frameCommanderView.network.title', 'Network and settings'),
    lead: t('frameCommanderView.network.lead', 'How the frame meets the others, the operators it starts with, and anything you want different from the defaults.'),
  },
  review: {
    title: t('frameCommanderView.review.title', 'Review and send'),
    lead: t('frameCommanderView.review.lead', 'Check the summary, tell us why, and send it. A person reads it.'),
  },
}))

const framesText = computed(() => (partners.value.length === 1
  ? t('frameCommanderView.live.framesOne', 'One frame on this network')
  : tp('frameCommanderView.live.framesMany', '{n} frames on this network', { n: partners.value.length })))

const othersText = computed(() => (otherRegistries.value === 1
  ? t('frameCommanderView.live.othersOne', 'plus one more registry they are connected to')
  : tp('frameCommanderView.live.othersMany', 'plus {n} more registries they are connected to', { n: otherRegistries.value })))

const pillars = computed(() => [
  {
    id: 'registry', icon: 'mdi:card-account-details', wide: false,
    tag: t('frameCommanderView.what.registryTag', 'Registry'),
    title: t('frameCommanderView.what.registryTitle', 'Identity for people and agents'),
    desc: t('frameCommanderView.what.registryDesc', 'Developer accounts, agents with their own DIDs, agent cards, and a signed registry card that tells the network who you are.'),
  },
  {
    id: 'treasury', icon: 'mdi:bank', wide: false,
    tag: t('frameCommanderView.what.treasuryTag', 'Treasury'),
    title: t('frameCommanderView.what.treasuryTitle', 'Your own currency'),
    desc: t('frameCommanderView.what.treasuryDesc', 'A unit issued once into your treasury. It funds new agents, collects the fees and backs the bond an agent posts before it sells services.'),
  },
  {
    id: 'ledger', icon: 'mdi:database-search-outline', wide: false,
    tag: t('frameCommanderView.what.ledgerTag', 'Ledger'),
    title: t('frameCommanderView.what.ledgerTitle', 'A ledger that can be audited'),
    desc: t('frameCommanderView.what.ledgerDesc', 'Every movement of value is an event in your own event store, and the supply is checked against it continuously.'),
  },
  {
    id: 'identity', icon: 'mdi:shield-key', wide: false,
    tag: t('frameCommanderView.what.identityTag', 'Identity'),
    title: t('frameCommanderView.what.identityTitle', 'Your own trust domain'),
    desc: t('frameCommanderView.what.identityDesc', 'Short-lived certificates for every service and, if you want, for your agents. Your services talk to each other over mutual TLS.'),
  },
  {
    id: 'federation', icon: 'mdi:connection', wide: true,
    tag: t('frameCommanderView.what.federationTag', 'Federation'),
    title: t('frameCommanderView.what.federationTitle', 'Peers when you choose'),
    desc: t('frameCommanderView.what.federationDesc', 'Invite frames and approve them. Agent cards travel between you, currencies swap through an exchange pool, and each frame decides how far it trusts the other.'),
  },
])

const journey = computed(() => [
  {
    id: 'request',
    title: t('frameCommanderView.journey.requestTitle', 'You ask'),
    desc: t('frameCommanderView.journey.requestDesc', 'Six short steps. The draft stays in this browser until you send it.'),
  },
  {
    id: 'review',
    title: t('frameCommanderView.journey.reviewTitle', 'We read it'),
    desc: t('frameCommanderView.journey.reviewDesc', 'A person reviews every request and may write back with questions, usually within seven business days.'),
  },
  {
    id: 'plan',
    title: t('frameCommanderView.journey.planTitle', 'We plan it'),
    desc: t('frameCommanderView.journey.planDesc', 'Your answers become the frame’s plan: name, currency, card, operators and settings.'),
  },
  {
    id: 'standup',
    title: t('frameCommanderView.journey.standupTitle', 'It stands up'),
    desc: t('frameCommanderView.journey.standupDesc', 'Ledger, treasury, trust domain, certificates and addresses are created on our infrastructure.'),
  },
  {
    id: 'federate',
    title: t('frameCommanderView.journey.federateTitle', 'It meets the network'),
    desc: t('frameCommanderView.journey.federateDesc', 'When you are ready, the frames you named receive an invitation. Both sides approve.'),
  },
])

const hostingOptions = computed(() => [
  {
    id: 'theprotocol', icon: 'mdi:server-network',
    title: t('frameCommanderView.frame.hostedTitle', 'Hosted by TheProtocol'),
    desc: tp('frameCommanderView.frame.hostedDesc', 'We run it for you under {domain}.', { domain: FRAME_DOMAIN }),
  },
  {
    id: 'self', icon: 'mdi:home',
    title: t('frameCommanderView.frame.selfTitle', 'On your own infrastructure'),
    desc: t('frameCommanderView.frame.selfDesc', 'You run it on your hardware, under your own hostname.'),
    // §HELLOFRAME: 'Later' only where the frame kit is not offered; where it is, an approved request gets the kit
    badge: frameKitEnabled.value ? undefined : t('frameCommanderView.frame.selfBadge', 'Later'),
  },
])

const themeOptions = computed(() => [
  { id: 'neural', swatch: '0, 210, 210', title: t('frameCommanderView.frame.neural', 'Neural'), desc: t('frameCommanderView.frame.neuralDesc', 'Cyan') },
  { id: 'sovereign', swatch: '220, 38, 38', title: t('frameCommanderView.frame.sovereign', 'Sovereign'), desc: t('frameCommanderView.frame.sovereignDesc', 'Red') },
])

const intentOptions = computed(() => [
  {
    id: 'federate_later', icon: 'mdi:connection',
    title: t('frameCommanderView.network.federateTitle', 'Federate'),
    desc: t('frameCommanderView.network.federateDesc', 'Stand up first, then invite the frames you choose.'),
  },
  {
    id: 'standalone', icon: 'mdi:shield-half-full',
    title: t('frameCommanderView.network.standaloneTitle', 'Standalone'),
    desc: t('frameCommanderView.network.standaloneDesc', 'A frame with no peers. Federation stays possible later.'),
  },
  {
    id: 'standalone_test_operator', icon: 'mdi:test-tube',
    title: t('frameCommanderView.network.testOperatorTitle', 'Standalone, with a test operator'),
    desc: t('frameCommanderView.network.testOperatorDesc', 'No peers, plus one cloud operator to try the operator side.'),
  },
])

// Who runs the frame decides the network licence it is issued when it federates (his words 2026-09-28): the same
// category list as the server's NETWORK_PLANS, each option naming its term.
const firstYear = (c: string): boolean => (FIRST_YEAR_CATEGORIES as readonly string[]).includes(c)
const licenceOptions = computed(() => {
  const titles: Record<string, string> = {
    private: t('frameCommanderView.network.licencePrivate', 'Private'),
    educational: t('frameCommanderView.network.licenceEducational', 'Educational'),
    research: t('frameCommanderView.network.licenceResearch', 'Research'),
    'non-profit': t('frameCommanderView.network.licenceNonProfit', 'Non-profit'),
    enterprise: t('frameCommanderView.network.licenceEnterprise', 'Enterprise'),
    government: t('frameCommanderView.network.licenceGovernment', 'Government'),
  }
  const icons: Record<string, string> = {
    private: 'mdi:account', educational: 'mdi:school', research: 'mdi:book-open-variant',
    'non-profit': 'mdi:account-group', enterprise: 'mdi:office-building', government: 'mdi:bank',
  }
  return LICENCE_CATEGORIES.map(id => ({
    id,
    icon: icons[id],
    title: titles[id],
    desc: firstYear(id) ? t('frameCommanderView.network.licenceFirstYear', 'Free for the first year') : t('frameCommanderView.network.licencePerpetual', 'Free, with no end date'),
  }))
})

const postureOptions = computed(() => [
  {
    id: 'pilot', icon: 'mdi:flag-outline',
    title: t('frameCommanderView.network.pilotTitle', 'Pilot'),
    desc: t('frameCommanderView.network.pilotDesc', 'A complete frame of your own to build on: rate limits relaxed, the test tools on, a mail relay optional.'),
  },
  {
    id: 'production', icon: 'mdi:shield-check',
    title: t('frameCommanderView.network.productionTitle', 'Production'),
    desc: t('frameCommanderView.network.productionDesc', 'For a frame people rely on: rate limits live, the test tools off, a mail relay required.'),
  },
])

const faq = computed(() => [
  {
    q: t('frameCommanderView.faq.q1', 'Why a frame and not a cloud operator?'),
    a: t('frameCommanderView.faq.a1', 'An operator runs under a frame, on its currency, its ledger and its trust domain. A frame has its own of all three. If registries and agents are all you need, an operator is the lighter road.'),
  },
  {
    q: t('frameCommanderView.faq.q2', 'What can change after stand-up?'),
    a: t('frameCommanderView.faq.a2', 'Your card (description, place, website, tags) can be edited from your console, and settings can change on request. The name, the trust domain and the currency are fixed at birth.'),
  },
  {
    q: t('frameCommanderView.faq.q3', 'Where does my draft live?'),
    a: t('frameCommanderView.faq.a3', 'Only in this browser, until you press Send. Nothing reaches us before that, and you can discard the draft at any time.'),
  },
  {
    q: t('frameCommanderView.faq.q4', 'Can I run it on my own hardware?'),
    a: frameKitEnabled.value
      ? t('frameCommanderView.faq.a4Kit', 'Yes. Ask for one here and choose "On your own infrastructure". Once a person approves the request, your frame page gives you the frame kit and the commands that stand it up on your servers.')
      : t('frameCommanderView.faq.a4', 'Not yet. Self-hosted frames wait for the open-source release. You can already ask for one, and we will write back when it is possible.'),
  },
  {
    q: t('frameCommanderView.faq.q5', 'Does federation happen by itself?'),
    a: t('frameCommanderView.faq.a5', 'No. After stand-up, the frames you named receive an invitation and both sides approve it. Until then your frame stands on its own.'),
  },
])

const SWITCH_LABELS = new Map(FRAME_FEATURE_SWITCHES.map(sw => [sw.key, sw.label]))
// Built, not spelled: a key that opens and closes with a quote reads as one literal key to the i18n gate.
const switchKey = (key: string): string => ['frameCommanderView', 'switches', key, 'label'].join('.')
const switchLabel = (key: string): string => tp(switchKey(key), SWITCH_LABELS.get(key) || key, {})

function optionWord(value: string): string {
  const words: Record<string, string> = {
    yes: t('frameCommanderView.options.yes', 'On'),
    no: t('frameCommanderView.options.no', 'Off'),
    off: t('frameCommanderView.options.off', 'Off'),
    shadow: t('frameCommanderView.options.shadow', 'Shadow'),
    enforce: t('frameCommanderView.options.enforce', 'Enforce'),
  }
  return words[value] || value
}

const titleOf = (options: { id: string; title: string }[], id: string): string => options.find(o => o.id === id)?.title || id

interface SummaryRow { label: string; value: string; mono?: boolean; missing?: boolean }
function row(label: string, value: string, mono = false): SummaryRow {
  return value ? { label, value, mono } : { label, value: t('frameCommanderView.review.notSet', 'Not set'), missing: true }
}

const summary = computed(() => {
  const changed = changedFeatures(draft.features)
  const intent = titleOf(intentOptions.value, draft.intent)
  const network = draft.intent === 'federate_later' && draft.partners.length
    ? tp('frameCommanderView.review.federateWith', 'Federate with {frames} after stand-up', { frames: draft.partners.join(', ') })
    : intent
  const licenceChoice = licenceOptions.value.find(o => o.id === draft.licence_category)
  const licence = draft.intent !== 'federate_later'
    ? t('frameCommanderView.review.licenceNone', 'None needed: a standalone frame runs without one')
    : licenceChoice ? `${licenceChoice.title} · ${licenceChoice.desc}` : ''
  const settings = Object.keys(changed).length
    ? Object.entries(changed).map(([k, v]) => `${switchLabel(k)}: ${optionWord(v)}`).join(', ')
    : t('frameCommanderView.review.defaults', 'All at their defaults')
  return [
    {
      step: 'contact' as StepId,
      title: stepLabels.value.contact,
      rows: [
        row(t('frameCommanderView.contact.organization', 'Organization'), draft.organization.trim()),
        row(t('frameCommanderView.contact.name', 'Your name'), draft.contact_name.trim()),
        row(t('frameCommanderView.contact.email', 'Email'), draft.email.trim(), true),
        row(t('frameCommanderView.review.account', 'Developer account'), draft.create_account
          ? t('frameCommanderView.review.accountYes', 'Create one for me')
          : t('frameCommanderView.review.accountNo', 'Not needed')),
      ],
    },
    {
      step: 'frame' as StepId,
      title: stepLabels.value.frame,
      rows: [
        row(t('frameCommanderView.frame.hosting', 'Where it runs'), titleOf(hostingOptions.value, draft.hosting)),
        row(t('frameCommanderView.frame.name', 'Frame name'), draft.frame_name.trim(), true),
        row(t('frameCommanderView.frame.displayName', 'Display name'), draft.display_name.trim()),
        row(t('frameCommanderView.frame.theme', 'Colour'), titleOf(themeOptions.value, draft.theme)),
        row(t('frameCommanderView.frame.console', 'Console'), addresses.value?.console || '', true),
      ],
    },
    {
      step: 'currency' as StepId,
      title: stepLabels.value.currency,
      rows: [
        row(t('frameCommanderView.currency.name', 'Currency name'), [draft.ticker, draft.currency_name.trim()].filter(Boolean).join(' · ')),
        row(t('frameCommanderView.currency.mint', 'Genesis issuance'), mintNumber.value === null ? '' : fmt(mintNumber.value, true), true),
        row(t('frameCommanderView.currency.grant', 'Genesis grant'), grantNumber.value === null ? '' : fmt(grantNumber.value, true), true),
      ],
    },
    {
      step: 'place' as StepId,
      title: stepLabels.value.place,
      rows: [
        row(t('frameCommanderView.place.location', 'City and country'), draft.location.trim()),
        row(t('frameCommanderView.review.coordinates', 'Coordinates'),
          draft.lat.trim() && draft.lng.trim() ? `${draft.lat.trim()}, ${draft.lng.trim()}` : '', true),
        row(t('frameCommanderView.place.website', 'Website'), draft.website.trim()),
        row(t('frameCommanderView.place.tags', 'Tags'), draft.tags.join(', ')),
      ],
    },
    {
      step: 'network' as StepId,
      title: stepLabels.value.network,
      rows: [
        row(t('frameCommanderView.review.network', 'Network'), network),
        row(t('frameCommanderView.review.licence', 'Network license'), licence),
        row(t('frameCommanderView.network.operators', 'Cloud operators'), String(draft.operators)),
        row(t('frameCommanderView.network.posture', 'Stage'), titleOf(postureOptions.value, draft.posture)),
        row(t('frameCommanderView.review.settings', 'Settings'), settings),
      ],
    },
  ]
})

// ── Validation shown to the person ───────────────────────────────────────────────────────────────────────
const ALL_FIELDS: DraftField[] = STEPS.flatMap(s => STEP_FIELDS[s])
const stepIndexOf = (field: DraftField): number => STEPS.findIndex(s => STEP_FIELDS[s].includes(field))

function bad(field: DraftField): boolean {
  if (serverIssues.value[field]) return true
  if (!issues.value[field]) return false
  return Boolean(touched[field]) || attempted.value[stepIndexOf(field)] === true
}

function err(field: DraftField): string {
  if (!bad(field)) return ''
  const server = serverIssues.value[field]
  if (server) return server
  const issue = issues.value[field]
  return issue ? tp(issue.key, issue.fallback, issue.params || {}) : ''
}

function touch(field: DraftField) {
  touched[field] = true
}

const stepHasIssues = (i: number): boolean => Object.keys(stepIssues(issues.value, STEPS[i])).length > 0
const stepDone = (i: number): boolean => i !== step.value && i < furthest.value && !stepHasIssues(i)
const stepFlagged = (i: number): boolean => i !== step.value && attempted.value[i] === true && stepHasIssues(i)
const stepClass = (i: number) => ({ 'is-current': i === step.value, 'is-done': stepDone(i), 'is-flagged': stepFlagged(i) })

// A refusal the registry named clears once the person changes that answer.
watch(() => ALL_FIELDS.map(f => JSON.stringify(draft[f])), (now, before) => {
  if (!before || !Object.keys(serverIssues.value).length) return
  const next = { ...serverIssues.value }
  ALL_FIELDS.forEach((f, i) => {
    if (now[i] !== before[i]) delete next[f]
  })
  serverIssues.value = next
})

// ── Moving through the steps ─────────────────────────────────────────────────────────────────────────────
const reducedMotion = (): boolean =>
  typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
const scrollBehavior = (): ScrollBehavior => (reducedMotion() ? 'auto' : 'smooth')

function scrollToId(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
}

function openForm() {
  scrollToId('fc-form')
  window.setTimeout(() => panelTitle.value?.focus({ preventScroll: true }), reducedMotion() ? 0 : 450)
}

function focusPanel() {
  nextTick(() => {
    panelTitle.value?.focus({ preventScroll: true })
    const nav = stepsRef.value
    if (nav && nav.getBoundingClientRect().top < 80) nav.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
  })
}

function focusFirstInvalid() {
  nextTick(() => {
    const el = panelRef.value?.querySelector<HTMLElement>('[aria-invalid="true"]')
    if (!el) return
    el.focus({ preventScroll: true })
    el.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
  })
}

function goTo(i: number) {
  if (i < 0 || i >= STEPS.length || i > furthest.value || i === step.value) return
  submitError.value = ''
  step.value = i
  focusPanel()
}

function next() {
  attempted.value[step.value] = true
  if (stepHasIssues(step.value)) {
    focusFirstInvalid()
    return
  }
  submitError.value = ''
  step.value += 1
  furthest.value = Math.max(furthest.value, step.value)
  focusPanel()
}

function back() {
  if (step.value === 0) return
  submitError.value = ''
  step.value -= 1
  focusPanel()
}

function onPrimary() {
  if (current.value === 'review') void submit()
  else next()
}

// ── Inputs ────────────────────────────────────────────────────────────────────────────────────────────────
const CHOICES: Record<'hosting' | 'theme' | 'intent' | 'posture' | 'licence_category', readonly string[]> = {
  hosting: ['theprotocol', 'self'],
  theme: ['neural', 'sovereign'],
  intent: ['federate_later', 'standalone', 'standalone_test_operator'],
  posture: ['pilot', 'production'],
  licence_category: LICENCE_CATEGORIES,
}

function choose(key: keyof typeof CHOICES, value: string) {
  if (CHOICES[key].includes(value)) (draft as unknown as Record<string, string>)[key] = value
}

function onFrameName(event: Event) {
  const el = event.target as HTMLInputElement
  const value = el.value.toLowerCase().replace(/\s+/g, '-')
  draft.frame_name = value
  if (el.value !== value) el.value = value
}

function onTicker(event: Event) {
  const el = event.target as HTMLInputElement
  const value = el.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 6)
  draft.ticker = value
  if (el.value !== value) el.value = value
}

function addTag() {
  const value = tagInput.value.replace(/,/g, ' ').trim()
  tagInput.value = ''
  if (!value || draft.tags.length >= LIMITS.tags) return
  const tag = value.slice(0, LIMITS.tag)
  if (!draft.tags.some(x => x.toLowerCase() === tag.toLowerCase())) draft.tags.push(tag)
}

function onTagKey(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    addTag()
  } else if (event.key === 'Backspace' && !tagInput.value && draft.tags.length) {
    draft.tags.pop()
  }
}

// Some phone keyboards report no key for the comma, so a typed comma also closes the tag.
watch(tagInput, value => {
  if (value.includes(',')) addTag()
})

function removeTag(i: number) {
  draft.tags.splice(i, 1)
  touch('tags')
}

function togglePartner(name: string) {
  const i = draft.partners.indexOf(name)
  if (i >= 0) draft.partners.splice(i, 1)
  else if (draft.partners.length < LIMITS.partners) draft.partners.push(name)
}

function bumpOperators(by: number) {
  draft.operators = Math.min(LIMITS.operators, Math.max(0, draft.operators + by))
}

function onSwitch(key: string, value: string) {
  draft.features = setFeature(draft.features, key, value)
}

function resetSwitches() {
  draft.features = defaultFeatures()
}

function onPick(point: { lat: number; lng: number }) {
  draft.lat = String(point.lat)
  draft.lng = String(point.lng)
  touch('lat')
  touch('lng')
}

// ── The draft on this device ─────────────────────────────────────────────────────────────────────────────
let saveTimer: ReturnType<typeof setTimeout> | undefined

function writeDraft() {
  saveTimer = undefined
  try {
    if (isPristine(draft)) {
      localStorage.removeItem(DRAFT_STORAGE_KEY)
      savedAt.value = null
      return
    }
    localStorage.setItem(DRAFT_STORAGE_KEY, serializeDraft(draft, step.value))
    savedAt.value = Date.now()
  } catch {
    savedAt.value = null
  }
}

watch([() => JSON.stringify(draft), step], () => {
  if (result.value) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(writeDraft, 400)
})

function forgetDraft() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = undefined
  try {
    localStorage.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    // Storage unavailable: there is nothing to forget.
  }
  savedAt.value = null
}

function resetForm() {
  Object.assign(draft, blankDraft())
  step.value = 0
  furthest.value = 0
  attempted.value = STEPS.map(() => false)
  for (const key of Object.keys(touched) as DraftField[]) delete touched[key]
  serverIssues.value = {}
  submitError.value = ''
  tagInput.value = ''
  advancedOpen.value = false
}

function discardDraft() {
  resetForm()
  forgetDraft()
  restored.value = false
  focusPanel()
}

// ── The network ───────────────────────────────────────────────────────────────────────────────────────────
async function loadNetwork() {
  networkState.value = 'loading'
  const quiet = { _skipLogoutOn401: true } as Record<string, unknown>
  try {
    const [list, info] = await Promise.all([
      apiClient.get('/federation/registries', quiet),
      apiClient.get('/federation/info', quiet).catch(() => null),
    ])
    registries.value = Array.isArray(list.data) ? list.data : []
    const name: unknown = info?.data?.registry_name
    selfName.value = typeof name === 'string' && name ? name : null
    networkState.value = 'ready'
    // A restored draft may name a frame the network no longer lists.
    const known = new Set(partners.value.map(p => p.name))
    if (draft.partners.some(n => !known.has(n))) draft.partners = draft.partners.filter(n => known.has(n))
  } catch {
    networkState.value = 'failed'
  }
}

// ── Sending ───────────────────────────────────────────────────────────────────────────────────────────────
const DRAFT_FIELD_NAMES = new Set<string>(ALL_FIELDS)
const REFUSAL_ALIASES: Record<string, DraftField> = { trust_domain: 'frame_name', hostname: 'hostname', features: 'partners' }

function fieldOf(loc: unknown): DraftField | null {
  if (!Array.isArray(loc)) return null
  for (let i = loc.length - 1; i >= 0; i--) {
    const part = String(loc[i])
    if (DRAFT_FIELD_NAMES.has(part)) return part as DraftField
    if (REFUSAL_ALIASES[part]) return REFUSAL_ALIASES[part]
  }
  return null
}

async function submit() {
  attempted.value = STEPS.map(() => true)
  const first = firstStepWithIssues(issues.value)
  if (first >= 0) {
    step.value = first
    submitError.value = t('frameCommanderView.submit.fix', 'Some answers need a look before the request can be sent.')
    focusFirstInvalid()
    return
  }
  if (!draft.accept_terms) {
    submitError.value = t('frameCommanderView.wizard.acceptRequired', 'Please accept the Terms of Service and the Federation Operator Terms before sending.')
    return
  }
  submitting.value = true
  submitError.value = ''
  serverIssues.value = {}
  const email = draft.email.trim()
  try {
    const { data } = await apiClient.post('/operators/request-frame', buildRequestPayload(draft), { _skipLogoutOn401: true } as Record<string, unknown>)
    result.value = {
      request_id: data?.request_id ? String(data.request_id) : null,
      account_created: Boolean(data?.account_created),
      magic_link_sent: Boolean(data?.magic_link_sent),
      email,
    }
    forgetDraft()
    resetForm()
    restored.value = false
    nextTick(() => {
      successRef.value?.focus({ preventScroll: true })
      successRef.value?.scrollIntoView({ behavior: scrollBehavior(), block: 'center' })
    })
  } catch (e: unknown) {
    const response = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response
    const status = response?.status
    const detail = response?.data?.detail
    const found: Partial<Record<DraftField, string>> = {}
    if (Array.isArray(detail)) {
      for (const d of detail as { loc?: unknown; msg?: unknown }[]) {
        const field = fieldOf(d?.loc)
        if (field && !found[field]) found[field] = String(d?.msg || '')
      }
    }
    const named = Object.keys(found) as DraftField[]
    if (named.length) {
      serverIssues.value = found
      const i = stepIndexOf(named[0])
      if (i >= 0) step.value = i
      focusFirstInvalid()
    }
    if (status === 429) submitError.value = t('frameCommanderView.submit.rateLimited', 'Too many requests from this address. Please try again in a few minutes.')
    else if (named.length) submitError.value = t('frameCommanderView.submit.refused', 'The registry refused some answers. They are marked on their step.')
    else if (typeof detail === 'string' && detail) submitError.value = detail
    else submitError.value = t('frameCommanderView.submit.failed', 'The request could not be sent. Try again, or write to commander@theprotocol.cloud.')
  } finally {
    submitting.value = false
  }
}

let copyTimer: ReturnType<typeof setTimeout> | undefined

async function copyId() {
  const id = result.value?.request_id
  if (!id) return
  try {
    await navigator.clipboard.writeText(id)
    copied.value = true
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => { copied.value = false }, 2000)
  } catch {
    copied.value = false
  }
}

function startAnother() {
  result.value = null
  copied.value = false
  nextTick(() => panelTitle.value?.focus({ preventScroll: true }))
}

// ── The preview stays in view ────────────────────────────────────────────────────────────────────────────
// The app's `html, body { overflow-x: hidden }` makes body a scroll container that never scrolls, so CSS
// `position: sticky` cannot hold the preview beside a long step (measured on V0363: it moved with the form). On wide
// screens the preview is moved with a transform instead: never above the form's top, never past its bottom.
const WIDE_SCREEN = '(min-width: 1101px)'
const PREVIEW_GAP = 24
let previewFrame = 0
let gridObserver: ResizeObserver | null = null

function headerOffset(): number {
  const header = document.querySelector<HTMLElement>('.dh-header')
  if (!header) return 0
  const position = getComputedStyle(header).position
  return position === 'fixed' || position === 'sticky' ? Math.max(0, header.getBoundingClientRect().bottom) : 0
}

function placePreview() {
  previewFrame = 0
  const grid = gridRef.value
  const aside = asideRef.value
  if (!grid || !aside) return
  if (!window.matchMedia(WIDE_SCREEN).matches) {
    aside.style.transform = ''
    return
  }
  const box = grid.getBoundingClientRect()
  const room = Math.max(box.height - aside.offsetHeight, 0)
  const shift = Math.min(Math.max(headerOffset() + PREVIEW_GAP - box.top, 0), room)
  aside.style.transform = shift > 0 ? `translateY(${Math.round(shift)}px)` : ''
}

function schedulePreview() {
  if (!previewFrame) previewFrame = requestAnimationFrame(placePreview)
}

// The wizard mounts behind a v-if and its height changes with every step and panel, so the observer follows the element.
watch([gridRef, step, advancedOpen], () => {
  gridObserver?.disconnect()
  gridObserver = null
  if (gridRef.value && typeof ResizeObserver !== 'undefined') {
    gridObserver = new ResizeObserver(schedulePreview)
    gridObserver.observe(gridRef.value)
  }
  schedulePreview()
}, { flush: 'post' })

// ── Lifecycle ─────────────────────────────────────────────────────────────────────────────────────────────
onMounted(() => {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(DRAFT_STORAGE_KEY)
  } catch {
    raw = null
  }
  const saved = restoreDraft(raw)
  if (saved) {
    Object.assign(draft, saved.draft)
    step.value = saved.step
    furthest.value = saved.step
    restored.value = true
    savedAt.value = Date.now()
    if (Object.keys(changedFeatures(saved.draft.features)).length) advancedOpen.value = true
  }
  void loadNetwork()
  window.addEventListener('scroll', schedulePreview, { passive: true })
  window.addEventListener('resize', schedulePreview)
  schedulePreview()
})

onBeforeUnmount(() => {
  // Leaving within the save delay still keeps the last keystrokes.
  if (saveTimer) {
    clearTimeout(saveTimer)
    if (!result.value) writeDraft()
  }
  if (copyTimer) clearTimeout(copyTimer)
  window.removeEventListener('scroll', schedulePreview)
  window.removeEventListener('resize', schedulePreview)
  gridObserver?.disconnect()
  if (previewFrame) cancelAnimationFrame(previewFrame)
})
</script>

<style scoped>
/* Design language: house card, translucent inputs, solid primary button, theme tokens only (Design_Language.md). */
.fc {
  --fc-line: rgba(var(--nc-primary-rgb), 0.18);
  --fc-border: var(--border, rgba(255, 255, 255, 0.12));
  --fc-text: var(--text, #e6e9ef);
  --fc-text-2: var(--text-secondary, #b8c0cc);
  --fc-muted: var(--muted, #7d8594);
  --fc-mono: var(--mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  position: relative; color: var(--fc-text); padding-bottom: 3rem;
}
.fc-wrap { max-width: 1180px; margin: 0 auto; padding-inline: clamp(16px, 3vw, 32px); box-sizing: border-box; }
.fc-card {
  background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid var(--fc-line); border-radius: 12px;
  backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8);
}
.fc-muted { margin: 0; font-size: 13px; color: var(--fc-muted); }
.fc-eyebrow {
  display: inline-block; font-family: var(--fc-mono); font-size: 11px; font-weight: 700;
  letter-spacing: 0.16em; text-transform: uppercase; color: var(--nc-primary);
}
.fc-pill {
  display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 10px;
  font-family: var(--fc-mono); font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
  color: var(--nc-primary); background: rgba(var(--nc-primary-rgb), 0.14); border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
}

/* Buttons */
.fc-btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  padding: 10px 18px; border-radius: 8px; cursor: pointer; text-decoration: none;
  font-size: 14px; font-weight: 600; color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
  transition: background 0.16s, border-color 0.16s, color 0.16s, box-shadow 0.16s, transform 0.08s, filter 0.16s;
}
.fc-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); }
.fc-btn:active:not(:disabled) { transform: translateY(1px); }
.fc-btn:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.3); }
.fc-btn:disabled { opacity: 0.55; cursor: default; }
.fc-btn--primary {
  color: #041014; background: var(--nc-primary); border-color: var(--nc-primary);
  box-shadow: 0 8px 24px -12px rgba(var(--nc-primary-rgb), 0.85);
}
.fc-btn--primary:hover:not(:disabled) { background: var(--nc-primary); filter: brightness(1.08); }
.fc-btn--ghost { color: var(--fc-text-2); background: transparent; border-color: var(--fc-border); }
.fc-btn--ghost:hover:not(:disabled) { color: var(--fc-text); background: rgba(255, 255, 255, 0.04); }
.fc-btn--small { padding: 5px 10px; font-size: 12px; }
.fc-btn-icon { flex: 0 0 auto; font-size: 16px; }
.fc-link {
  display: inline-flex; align-items: center; gap: 4px; padding: 0; border: 0; background: none;
  cursor: pointer; font-size: 12px; font-weight: 600; color: var(--nc-primary);
}
.fc-link:hover { text-decoration: underline; }
.fc-link:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: 2px; border-radius: 3px; }
.fc-spin { animation: fc-spin 0.9s linear infinite; }
@keyframes fc-spin { to { transform: rotate(360deg); } }

/* Hero */
.fc-hero { position: relative; overflow: hidden; padding-block: clamp(2.5rem, 6vw, 5rem) 2.5rem; }
.fc-hero::before {
  content: ''; position: absolute; top: -30%; right: -12%; width: 62%; height: 150%; pointer-events: none;
  background: radial-gradient(closest-side, rgba(var(--nc-primary-rgb), 0.13), transparent);
}
.fc-hero-grid { position: relative; display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr); gap: clamp(20px, 4vw, 48px); align-items: center; }
.fc-chip {
  display: inline-flex; align-items: center; gap: 8px; margin-bottom: 1.2rem; padding: 5px 12px; border-radius: 12px;
  font-family: var(--fc-mono); font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--nc-primary); background: rgba(var(--nc-primary-rgb), 0.08); border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
}
.fc-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--nc-primary); box-shadow: 0 0 8px var(--nc-primary); animation: fc-blink 2.4s ease-in-out infinite; }
@keyframes fc-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
.fc-h1 { margin: 0 0 1rem; font-size: clamp(38px, 6vw, 68px); font-weight: 700; line-height: 1.04; letter-spacing: -0.02em; color: #fff; }
.fc-h1-accent {
  background: linear-gradient(90deg, var(--nc-primary), rgba(var(--nc-primary-rgb), 0.65));
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.fc-lead { margin: 0 0 0.6rem; max-width: 620px; font-size: clamp(16px, 1.7vw, 20px); line-height: 1.5; color: var(--fc-text); }
.fc-sub { margin: 0 0 1.6rem; max-width: 620px; font-size: 14px; line-height: 1.65; color: var(--fc-text-2); }
.fc-hero-actions { display: flex; flex-wrap: wrap; gap: 10px; }

/* The live network card */
.fc-live { display: flex; flex-direction: column; gap: 12px; padding: 18px 20px; }
.fc-live-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.fc-live-badge {
  display: inline-flex; align-items: center; gap: 6px; font-family: var(--fc-mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase; color: #10b981;
}
.fc-live-dot { width: 7px; height: 7px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981; animation: fc-blink 2s ease-in-out infinite; }
.fc-live-count { margin: 0; font-size: 20px; font-weight: 700; color: #fff; }
.fc-live-list { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 0; list-style: none; }
.fc-live-row {
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 10px; border-radius: 8px;
  background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.05);
}
.fc-live-mark { width: 8px; height: 8px; border-radius: 2px; transform: rotate(45deg); background: var(--nc-primary); box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.7); }
.fc-live-name { font-size: 13px; font-weight: 700; color: var(--fc-text); }
.fc-live-host { margin-left: auto; font-family: var(--fc-mono); font-size: 11px; color: var(--fc-muted); overflow-wrap: anywhere; }
.fc-live-foot { margin: 0; font-size: 12px; color: var(--fc-muted); }

/* Sections */
.fc-sec { padding-block: clamp(2.5rem, 5vw, 4rem); }
.fc-sec-head { max-width: 760px; margin-bottom: 1.8rem; }
.fc-h2 { margin: 8px 0; font-size: clamp(24px, 3vw, 32px); font-weight: 700; letter-spacing: -0.01em; color: #fff; }
.fc-sec-lead { margin: 0; font-size: 14px; line-height: 1.7; color: var(--fc-text-2); }

.fc-pillars { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.fc-pillar {
  display: flex; flex-direction: column; gap: 6px; padding: 20px 22px;
  animation: fc-rise 560ms cubic-bezier(0.22, 1, 0.36, 1) both; animation-delay: calc(80ms + var(--i, 0) * 70ms);
  transition: border-color 0.2s, transform 0.2s;
}
.fc-pillar:hover { border-color: rgba(var(--nc-primary-rgb), 0.32); transform: translateY(-2px); }
.fc-pillar--wide { grid-column: 1 / -1; }
.fc-pillar-icon { margin-bottom: 4px; font-size: 26px; color: var(--nc-primary); }
.fc-pillar-tag { font-family: var(--fc-mono); font-size: 10px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase; color: var(--fc-muted); }
.fc-pillar-title { margin: 0; font-size: 17px; font-weight: 700; color: #fff; }
.fc-pillar-desc { margin: 0; font-size: 13px; line-height: 1.65; color: var(--fc-text-2); }
@keyframes fc-rise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }

.fc-journey { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 0; padding: 0; list-style: none; }
.fc-journey-step {
  position: relative; display: flex; flex-direction: column; gap: 10px; padding: 16px; border-radius: 12px;
  border: 1px solid var(--fc-line); background: rgba(var(--nc-primary-rgb), 0.025);
}
.fc-journey-step:not(:last-child)::after {
  content: ''; position: absolute; top: 31px; right: -13px; width: 14px; height: 1px; background: rgba(var(--nc-primary-rgb), 0.45);
}
.fc-journey-num {
  display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border-radius: 50%;
  font-family: var(--fc-mono); font-size: 13px; font-weight: 700; color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
}
.fc-journey-title { margin: 0 0 4px; font-size: 14px; font-weight: 700; color: #fff; }
.fc-journey-desc { margin: 0; font-size: 12px; line-height: 1.6; color: var(--fc-text-2); }

/* The wizard */
.fc-sec--form { scroll-margin-top: 88px; }
.fc-steps { margin-bottom: 16px; scroll-margin-top: 96px; }
.fc-steps-list { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 6px; margin: 0; padding: 0; list-style: none; }
.fc-step {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 10px; border-radius: 9px; cursor: pointer;
  text-align: left; color: var(--fc-muted); background: transparent; border: 1px solid transparent;
  transition: background 0.16s, border-color 0.16s, color 0.16s;
}
.fc-step:hover:not(:disabled) { color: var(--fc-text); background: rgba(255, 255, 255, 0.03); }
.fc-step:disabled { cursor: default; opacity: 0.5; }
.fc-step:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.3); }
.fc-step-num {
  display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%;
  font-family: var(--fc-mono); font-size: 12px; font-weight: 700; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.16);
}
.fc-step-label { overflow: hidden; font-size: 13px; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; }
.fc-step.is-current { color: #fff; background: rgba(var(--nc-primary-rgb), 0.1); border-color: rgba(var(--nc-primary-rgb), 0.35); }
.fc-step.is-current .fc-step-num { color: #041014; background: var(--nc-primary); border-color: var(--nc-primary); box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.6); }
.fc-step.is-done .fc-step-num { color: var(--nc-primary); background: rgba(var(--nc-primary-rgb), 0.1); border-color: rgba(var(--nc-primary-rgb), 0.5); }
.fc-step.is-flagged { color: #fbbf24; }
.fc-step.is-flagged .fc-step-num { color: #f59e0b; background: rgba(245, 158, 11, 0.1); border-color: rgba(245, 158, 11, 0.5); }
.fc-steps-track { height: 3px; margin-top: 10px; overflow: hidden; border-radius: 2px; background: rgba(255, 255, 255, 0.06); }
.fc-steps-fill {
  display: block; height: 100%; background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.5), var(--nc-primary));
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.6); transition: width 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}

.fc-wizard-grid { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
.fc-panel { display: flex; flex-direction: column; gap: 20px; min-width: 0; padding: clamp(18px, 2.4vw, 28px); }
.fc-aside { position: relative; display: flex; flex-direction: column; gap: 10px; will-change: transform; }
.fc-aside-note { display: flex; gap: 6px; margin: 0; font-size: 12px; line-height: 1.5; color: var(--fc-muted); }

.fc-notice {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 10px 12px; border-radius: 9px;
  font-size: 13px; color: var(--fc-text-2); background: rgba(var(--nc-primary-rgb), 0.07); border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
}
.fc-notice-icon { font-size: 18px; color: var(--nc-primary); }
.fc-notice .fc-link { margin-left: auto; }

.fc-panel-head { display: flex; flex-direction: column; gap: 4px; }
.fc-panel-count { font-family: var(--fc-mono); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--fc-muted); }
.fc-panel-title { margin: 0; font-size: 22px; font-weight: 700; color: #fff; outline: none; }
.fc-panel-lead { margin: 0; font-size: 13px; line-height: 1.6; color: var(--fc-text-2); }

.fc-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 18px; animation: fc-fade 260ms ease both; }
@keyframes fc-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.fc-fields-wide { grid-column: 1 / -1; }
.fc-field-stack { display: flex; flex-direction: column; gap: 6px; min-width: 0; }

.fc-input {
  box-sizing: border-box; width: 100%; min-width: 0; padding: 10px 12px; border-radius: 7px;
  font-size: 14px; color: var(--fc-text); background: rgba(0, 0, 0, 0.35); border: 1px solid var(--fc-border);
  transition: border-color 0.16s, box-shadow 0.16s;
}
.fc-input::placeholder { color: rgba(255, 255, 255, 0.28); }
.fc-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.55); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.12); }
.fc-input[aria-invalid='true'] { border-color: rgba(239, 68, 68, 0.65); }
.fc-input[aria-invalid='true']:focus { box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.16); }
.fc-input--mono { font-family: var(--fc-mono); font-size: 13px; }
.fc-input--ticker { letter-spacing: 0.12em; }
.fc-textarea { min-height: 84px; resize: vertical; font-family: inherit; line-height: 1.55; }
.fc-affix { display: flex; align-items: stretch; min-width: 0; }
.fc-affix .fc-input { border-top-right-radius: 0; border-bottom-right-radius: 0; }
.fc-affix-tail {
  display: inline-flex; align-items: center; padding: 0 10px; white-space: nowrap;
  font-family: var(--fc-mono); font-size: 12px; color: var(--fc-muted);
  background: rgba(255, 255, 255, 0.03); border: 1px solid var(--fc-border); border-left: 0; border-radius: 0 7px 7px 0;
}
.fc-suggest {
  display: inline-flex; align-self: flex-start; align-items: center; gap: 5px; padding: 4px 10px; border-radius: 12px; cursor: pointer;
  font-family: var(--fc-mono); font-size: 12px; color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.08); border: 1px dashed rgba(var(--nc-primary-rgb), 0.4);
}
.fc-suggest:hover { background: rgba(var(--nc-primary-rgb), 0.16); }

.fc-check {
  position: relative; display: flex; align-items: flex-start; gap: 12px; padding: 12px 14px; border-radius: 10px; cursor: pointer;
  background: rgba(0, 0, 0, 0.22); border: 1px solid var(--fc-border);
}
.fc-check:hover { border-color: rgba(var(--nc-primary-rgb), 0.35); }
.fc-check-input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.fc-check-box {
  display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: 20px; height: 20px; margin-top: 1px; border-radius: 5px;
  font-size: 14px; color: transparent; border: 1.5px solid rgba(255, 255, 255, 0.3); transition: background 0.16s, border-color 0.16s, color 0.16s;
}
.fc-check-input:checked + .fc-check-box { color: #041014; background: var(--nc-primary); border-color: var(--nc-primary); }
.fc-check-input:focus-visible + .fc-check-box { box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.3); }
.fc-check-copy { display: flex; flex-direction: column; gap: 3px; }
.fc-check-title { font-size: 13px; font-weight: 600; color: var(--fc-text); }
.fc-check-sub { font-size: 12px; color: var(--fc-muted); }

.fc-addresses { padding: 14px 16px; border-radius: 10px; background: rgba(0, 0, 0, 0.25); border: 1px dashed rgba(var(--nc-primary-rgb), 0.28); }
.fc-addresses-head { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; font-size: 12px; font-weight: 700; letter-spacing: 0.04em; color: var(--fc-text-2); }
.fc-addresses-list { display: grid; gap: 6px; margin: 0; }
.fc-addresses-list > div { display: grid; grid-template-columns: 150px minmax(0, 1fr); gap: 10px; align-items: baseline; }
.fc-addresses-list dt { font-size: 12px; color: var(--fc-muted); }
.fc-addresses-list dd { margin: 0; font-family: var(--fc-mono); font-size: 12px; color: var(--nc-primary); overflow-wrap: anywhere; }

.fc-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.fc-stat { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 8px; background: rgba(var(--nc-primary-rgb), 0.03); border: 1px solid var(--fc-border); }
.fc-stat-value { font-family: var(--fc-mono); font-size: 17px; font-weight: 700; color: var(--nc-primary); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.fc-stat-label { font-size: 11px; line-height: 1.45; color: var(--fc-muted); }

.fc-tags {
  box-sizing: border-box; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; min-height: 44px; padding: 6px 8px; border-radius: 7px;
  background: rgba(0, 0, 0, 0.35); border: 1px solid var(--fc-border);
}
.fc-tags:focus-within { border-color: rgba(var(--nc-primary-rgb), 0.55); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.12); }
.fc-tag {
  display: inline-flex; align-items: center; gap: 4px; padding: 3px 4px 3px 10px; border-radius: 12px;
  font-size: 12px; color: var(--fc-text); background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
}
.fc-tag-x {
  display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 50%;
  cursor: pointer; font-size: 12px; color: var(--fc-text-2); background: transparent;
}
.fc-tag-x:hover { color: #fff; background: rgba(255, 255, 255, 0.1); }
.fc-tags-input { flex: 1; min-width: 120px; padding: 4px; border: 0; outline: none; font-size: 14px; color: var(--fc-text); background: transparent; }

.fc-partners { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
.fc-partner {
  display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 9px; cursor: pointer; text-align: left; color: inherit;
  background: rgba(0, 0, 0, 0.25); border: 1px solid var(--fc-border); transition: border-color 0.16s, background 0.16s;
}
.fc-partner:hover { border-color: rgba(var(--nc-primary-rgb), 0.35); }
.fc-partner:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.3); }
.fc-partner.is-on { background: rgba(var(--nc-primary-rgb), 0.08); border-color: rgba(var(--nc-primary-rgb), 0.6); }
.fc-partner-check {
  display: inline-flex; flex: 0 0 auto; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 5px;
  font-size: 14px; color: transparent; border: 1.5px solid rgba(255, 255, 255, 0.3);
}
.fc-partner.is-on .fc-partner-check { color: #041014; background: var(--nc-primary); border-color: var(--nc-primary); }
.fc-partner-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fc-partner-name { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 13px; font-weight: 700; color: var(--fc-text); }
.fc-partner-host { font-family: var(--fc-mono); font-size: 11px; color: var(--fc-muted); overflow-wrap: anywhere; }

.fc-stepper { display: inline-flex; align-self: flex-start; align-items: center; gap: 4px; padding: 4px; border-radius: 9px; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--fc-border); }
.fc-stepper-btn {
  display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 0; border-radius: 7px; cursor: pointer;
  font-size: 18px; color: var(--nc-primary); background: rgba(var(--nc-primary-rgb), 0.1);
}
.fc-stepper-btn:disabled { opacity: 0.35; cursor: default; }
.fc-stepper-btn:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.55); }
.fc-stepper-value { min-width: 44px; text-align: center; font-family: var(--fc-mono); font-size: 18px; font-weight: 700; color: #fff; }

.fc-advanced { overflow: hidden; border-radius: 12px; border: 1px solid var(--fc-line); background: rgba(var(--nc-primary-rgb), 0.025); }
.fc-advanced.is-open { border-color: rgba(var(--nc-primary-rgb), 0.3); }
.fc-advanced-head { display: flex; align-items: center; gap: 12px; width: 100%; padding: 14px 16px; border: 0; cursor: pointer; text-align: left; color: inherit; background: transparent; }
.fc-advanced-head:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
.fc-advanced-head:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: -2px; }
.fc-advanced-icon { font-size: 22px; color: var(--nc-primary); }
.fc-advanced-copy { display: flex; flex: 1; flex-direction: column; gap: 2px; min-width: 0; }
.fc-advanced-title { font-size: 15px; font-weight: 700; color: #fff; }
.fc-advanced-lead { font-size: 12px; line-height: 1.5; color: var(--fc-muted); }
.fc-advanced-chevron { font-size: 20px; color: var(--fc-muted); transition: transform 0.2s; }
.fc-advanced.is-open .fc-advanced-chevron { transform: rotate(180deg); }
.fc-advanced-body { padding: 0 14px 14px; }
@media (max-width: 640px) { .fc-advanced-body { padding: 0 10px 12px; } }

.fc-warnings { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 12px 14px; border-radius: 10px; list-style: none; background: rgba(245, 158, 11, 0.07); border: 1px solid rgba(245, 158, 11, 0.28); }
.fc-warnings li { display: flex; gap: 8px; font-size: 12px; line-height: 1.5; color: #fcd34d; }
.fc-li-icon { flex: 0 0 auto; margin-top: 1px; font-size: 15px; }

.fc-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.fc-summary-block { min-width: 0; padding: 12px 14px; border-radius: 10px; background: rgba(0, 0, 0, 0.22); border: 1px solid rgba(255, 255, 255, 0.08); }
.fc-summary-block:last-child:nth-child(odd) { grid-column: 1 / -1; }
.fc-summary-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.fc-summary-title { margin: 0; font-family: var(--fc-mono); font-size: 11px; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; color: var(--nc-primary); }
.fc-summary-list { display: flex; flex-direction: column; gap: 5px; margin: 0; }
.fc-summary-row { display: grid; grid-template-columns: minmax(96px, 38%) minmax(0, 1fr); gap: 10px; font-size: 12px; }
.fc-summary-row dt { color: var(--fc-muted); }
.fc-summary-row dd { margin: 0; color: var(--fc-text); overflow-wrap: anywhere; }
.fc-summary-row dd.is-mono { font-family: var(--fc-mono); }
.fc-summary-row dd.is-missing { font-style: italic; color: var(--fc-muted); }

.fc-json { border-radius: 10px; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.08); }
.fc-json-summary { padding: 10px 14px; cursor: pointer; font-size: 12px; font-weight: 600; color: var(--fc-text-2); }
.fc-json-body { max-height: 320px; margin: 0; padding: 0 14px 14px; overflow: auto; white-space: pre; font-family: var(--fc-mono); font-size: 11.5px; line-height: 1.55; color: var(--fc-text-2); }

.fc-submit-error { display: flex; gap: 8px; margin: 0; padding: 10px 12px; border-radius: 9px; font-size: 13px; color: #fca5a5; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.35); }
.fc-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding-top: 16px; border-top: 1px solid rgba(255, 255, 255, 0.06); }
.fc-draft-state { display: inline-flex; flex: 1; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 0; font-size: 12px; color: var(--fc-muted); }

.fc-success {
  display: flex; flex-direction: column; align-items: center; gap: 14px; max-width: 720px; margin: 0 auto;
  padding: clamp(24px, 4vw, 40px); text-align: center; outline: none;
  animation: fc-rise 480ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.fc-success-badge {
  display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 64px; border-radius: 50%;
  font-size: 34px; color: #10b981; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.4); box-shadow: 0 0 30px rgba(16, 185, 129, 0.25);
}
.fc-success-title { margin: 0; font-size: 24px; font-weight: 700; color: #fff; }
.fc-success-lead { max-width: 520px; margin: 0; font-size: 14px; line-height: 1.6; color: var(--fc-text-2); }
.fc-success-id {
  display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 10px; padding: 10px 14px; border-radius: 10px;
  background: rgba(0, 0, 0, 0.3); border: 1px solid var(--fc-border);
}
.fc-success-id-label { font-size: 12px; color: var(--fc-muted); }
.fc-success-id code { font-family: var(--fc-mono); font-size: 13px; color: var(--nc-primary); overflow-wrap: anywhere; }
.fc-success-list { display: flex; flex-direction: column; gap: 8px; margin: 0; padding: 0; list-style: none; text-align: left; }
.fc-success-list li { display: flex; gap: 8px; font-size: 13px; color: var(--fc-text-2); }

.fc-faq-wrap { max-width: 900px; }
.fc-faq { display: flex; flex-direction: column; gap: 10px; }
.fc-faq-q {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; cursor: pointer; list-style: none;
  font-size: 15px; font-weight: 600; color: var(--fc-text);
}
.fc-faq-q::-webkit-details-marker { display: none; }
.fc-faq-q:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: -2px; border-radius: 12px; }
.fc-faq-chevron { flex: 0 0 auto; font-size: 20px; color: var(--fc-muted); transition: transform 0.2s; }
.fc-faq-item[open] .fc-faq-chevron { color: var(--nc-primary); transform: rotate(180deg); }
.fc-faq-a { margin: 0; padding: 0 18px 16px; font-size: 13px; line-height: 1.7; color: var(--fc-text-2); }
.fc-footer { margin: 1.6rem 0 0; font-size: 13px; color: var(--fc-muted); }
/* §FESUITE: a link inside a sentence is told apart by more than its colour (WCAG 1.4.1) */
.fc-footer a { color: var(--nc-primary); text-decoration: underline; text-underline-offset: 2px; }

@media (max-width: 1100px) {
  .fc-wizard-grid { grid-template-columns: minmax(0, 1fr); }
  .fc-aside { position: static; }
  .fc-journey { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .fc-journey-step:not(:last-child)::after { display: none; }
  .fc-journey-step:last-child:nth-child(odd) { grid-column: 1 / -1; }
}
@media (max-width: 900px) {
  .fc-hero-grid, .fc-pillars, .fc-summary { grid-template-columns: minmax(0, 1fr); }
  .fc-stats { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 760px) {
  .fc-steps-list { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; }
  .fc-steps-item { flex: 0 0 auto; }
  .fc-step { padding: 6px; }
  .fc-step:not(.is-current) .fc-step-label { display: none; }
  .fc-fields, .fc-journey { grid-template-columns: minmax(0, 1fr); }
  .fc-addresses-list > div { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .fc-hero-actions .fc-btn { flex: 1 1 auto; }
}
@media (max-width: 480px) {
  .fc-affix-tail { display: none; }
  .fc-affix .fc-input { border-radius: 7px; }
  .fc-summary-row { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .fc-actions { gap: 8px; }
  .fc-draft-state { order: 3; flex-basis: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .fc-pillar, .fc-fields, .fc-success { animation: none; }
  .fc-chip-dot, .fc-live-dot { animation: none; }
  .fc-steps-fill { transition: none; }
}
.fc-accept { display: flex; gap: 10px; align-items: flex-start; font-size: 0.92rem; line-height: 1.45; margin: 4px 0 10px; }
.fc-accept input { margin-top: 4px; }
.fc-accept a { text-decoration: underline; }
</style>
