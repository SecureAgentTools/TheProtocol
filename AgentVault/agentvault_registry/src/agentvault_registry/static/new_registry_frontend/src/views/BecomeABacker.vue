<template>
  <div class="bav-root nc-page">
    <!-- §FLARESHOP (2026-08-16) — THE LANE GATE.
         When FIAT_ONRAMP_ENABLED is false (which is every frame in this fleet)
         this view used to render its whole pitch — "Be in the founding chapter,
         receive AVT credits, wear your flare" — over a small amber note, with
         the tier cards silently absent because /fiat/tiers 503s. That is an
         offer surface for a lane that cannot transact. The Commander's call:
         the entry stays in the sidebar, the VIEW becomes inaccessible.
         So: one honest state, and a door to the lane that IS open here. -->
    <section v-if="onrampDisabled || fiatNotApplicable" class="bav-gate" data-testid="bav-lane-gate" data-tour="fiat-gate">
      <div class="bav-gate-emblem" aria-hidden="true">
        <Icon name="mdi:currency-eur-off" class="w-12 h-12" />
      </div>
      <h1 class="bav-gate-title">{{ t('backerView.gate.title', 'The euro lane is closed on this registry') }}</h1>
      <p class="bav-gate-sub">
        {{ t('backerView.gate.sub', 'No card payments are offered here and no euros are accepted. This is a deliberate operator setting, not an outage: platform credits on this frame are granted and transferred inside the network.') }}
      </p>
      <div class="bav-gate-actions">
        <router-link to="/flare-shop" class="bav-gate-cta" data-testid="bav-gate-shop">
          <Icon name="mdi:store-outline" class="w-4 h-4" />
          {{ t('backerView.gate.shop', 'Buy flares with this frame\'s own currency') }}
        </router-link>
        <router-link v-if="!fiatNotApplicable" to="/founders-wall" class="bav-gate-link" data-testid="bav-gate-wall">
          {{ t('backerView.gate.wall', 'See the Founders Wall') }}
        </router-link>
      </div>
      <p class="bav-gate-foot">
        {{ t('backerView.gate.foot', 'An operator opens this lane with FIAT_ONRAMP_ENABLED on a genesis registry.') }}
      </p>
    </section>

    <!-- Hero — emotive, mission-first -->
    <template v-else>
    <header class="bav-hero">
      <div class="bav-chip">
        <span class="bav-chip-dot"></span>
        {{ t('backerView.hero.chip') }}
      </div>
      <!-- §FEFRAME W2: the on-ramp is offered where the registry says it is (fiat_onramp_enabled), never by the
           unit's name. The onrampDisabled case no longer reaches here — it renders the lane gate above instead of a
           note stapled to a live pitch (§FLARESHOP). -->
      <div v-if="fiatNotApplicable" class="bav-fx-notice" role="note">
        This registry settles in <strong>{{ localCurrency }}</strong>. It does not sell through the fiat on-ramp.
      </div>
      <h1 class="bav-h1" data-tour="fiat-hero">
        <template v-if="t('backerView.hero.h1Prefix')">{{ t('backerView.hero.h1Prefix') }} </template><span class="bav-h1-accent">{{ t('backerView.hero.h1Accent') }}</span>
      </h1>
      <p class="bav-tagline">
        {{ t('backerView.hero.tagline', { unit: localCurrency }) }}
      </p>

      <!-- Live counter — total backers + AVT distributed -->
      <div class="bav-live-counter" v-if="publicStats">
        <span class="bav-live-num">{{ animBackers.toLocaleString(appLocale()) }}</span>
        <span class="bav-live-label">{{ animBackers === 1 ? t('backerView.live.backerSingular') : t('backerView.live.backerPlural') }}</span>
        <span class="bav-live-sep">·</span>
        <span class="bav-live-num">{{ animAvt.toLocaleString(appLocale()) }}</span>
        <span class="bav-live-label">{{ t('backerView.live.label', { unit: localCurrency }) }}</span>
      </div>

      <!-- Trust strip -->
      <div class="bav-trust-strip">
        <div class="bav-trust-item" :title="TRUST_TIPS.minting">
          <Icon name="mdi:shield-check" class="bav-trust-icon" />
          <span>{{ t('backerView.live.mainframeOnly') }}</span>
        </div>
        <div class="bav-trust-item" :title="TRUST_TIPS.mica">
          <Icon name="mdi:scale-balance" class="bav-trust-icon" />
          <span>{{ t('backerView.live.micaSafe') }}</span>
        </div>
        <div class="bav-trust-item" :title="TRUST_TIPS.audit">
          <Icon name="mdi:eye-check-outline" class="bav-trust-icon" />
          <span>{{ t('backerView.live.auditedSupply') }}</span>
        </div>
        <div class="bav-trust-item" :title="TRUST_TIPS.opensource">
          <Icon name="mdi:source-branch" class="bav-trust-icon" />
          <span>{{ t('backerView.live.openSource') }}</span>
        </div>
      </div>

      <!-- Live social-proof ticker -->
      <transition name="bav-ticker-fade" mode="out-in">
        <div
          v-if="tickerCurrent"
          :key="tickerKey"
          class="bav-ticker"
        >
          <FlareBadge :tier="tickerCurrent.flare_tier" size="xs" :show-label="false" />
          <span class="bav-ticker-text">
            anonymous backer · <strong>{{ Number(tickerCurrent.amount_avt).toLocaleString(appLocale()) }}</strong> {{ localCurrency }}
            <span class="bav-ticker-time">{{ formatAgo(tickerCurrent.seconds_ago) }}</span>
          </span>
        </div>
      </transition>
    </header>

    <!-- Payment logos — prominent trust strip directly under hero (Phase H, 2026-05-09) -->
    <PaymentLogos v-if="!onrampDisabled" size="lg" class="bav-payment-strip" data-tour="fiat-methods" />

    <!-- Tier cards — named, emotive, backer-framed -->
    <section v-if="!onrampDisabled" class="bav-tiers-grid" data-tour="fiat-tiers">
      <div
        v-for="(tier, i) in backerTiers"
        :key="tier.label"
        class="bav-backer-tier"
        :class="{
          'bav-backer-tier-active': activeTier === tier.label,
          [`bav-backer-tier-${i + 1}`]: true,
        }"
        @click="selectTier(tier)"
      >
        <div class="bav-tier-corner-mark">{{ i + 1 }}</div>
        <div class="bav-tier-name-row">
          <FlareBadge
            :tier="tierCardFlare(tier.label)"
            size="md"
            :show-label="false"
            class="bav-tier-flare"
          />
          <h3 class="bav-tier-name">{{ tier.displayName }}</h3>
        </div>
        <p class="bav-tier-tagline">{{ tier.tagline }}</p>
        <div class="bav-tier-amount">
          <span class="bav-tier-amount-from">{{ t('backerView.tier.from') }}</span>
          <span class="bav-tier-amount-eur">€{{ tier.floor }}</span>
        </div>
        <ul class="bav-tier-perks">
          <li><Icon name="mdi:check-circle-outline" /> <strong>{{ tier.rate }}</strong> {{ t('backerView.tier.avtPerEur', { unit: localCurrency }) }}</li>
          <li v-if="tier.bonus"><Icon name="mdi:gift-outline" /> {{ tier.bonus }} {{ t('backerView.tier.avtBonus', { unit: localCurrency }) }}</li>
          <li><Icon name="mdi:shield-star-outline" /> <strong>{{ tier.displayName }}</strong> {{ t('backerView.tier.profileFlare') }}</li>
          <li><Icon name="mdi:robot-outline" /> {{ t('backerView.tier.applyFlare') }}</li>
          <li v-if="i >= 2"><Icon name="mdi:account-voice" /> {{ t('backerView.tier.founderVoice') }}</li>
        </ul>

        <!-- Founder scarcity (only on tier 3). Flips to a SOLD-OUT pill once
             the 100 slots are filled — buyer still gets the +50% bonus in units, but
             the cosmetic flare is downgraded to Architect (cap enforced
             server-side in _grant_flare). 2026-05-10 update. -->
        <div v-if="i === 2 && publicStats" class="bav-founder-scarcity">
          <div class="bav-founder-bar" :class="{ 'bav-founder-bar-full': founderSlotsSoldOut }">
            <div
              class="bav-founder-bar-fill"
              :style="{ width: `${Math.min(100, (publicStats.founder_count / 100) * 100)}%` }"
            ></div>
          </div>
          <div v-if="!founderSlotsSoldOut" class="bav-founder-text">
            <strong>{{ publicStats.founder_count }}</strong> / 100 {{ t('backerView.scarcity.founders') }}
            <span class="bav-founder-rem">· {{ publicStats.founder_slots_remaining }} {{ t('backerView.scarcity.left') }}</span>
          </div>
          <div v-else class="bav-founder-text bav-founder-soldout">
            <strong>100 / 100</strong> {{ t('backerView.scarcity.claimedForever') }}
            <span class="bav-founder-rem">· {{ t('backerView.scarcity.soldoutNote', { unit: localCurrency }) }}</span>
          </div>
        </div>

        <button class="bav-tier-cta" @click.stop="selectTier(tier)">
          {{ activeTier === tier.label ? '✓ ' + t('backerView.tier.selected') : t('backerView.tier.chooseTier') }}
        </button>
      </div>
    </section>

    <section v-if="!onrampDisabled" class="bav-card">
      <div class="bav-card-head">
        <Icon name="mdi:cart-arrow-down" class="bav-card-head-icon" />
        <h2>{{ t('backerView.form.confirmTitle') }}</h2>
      </div>

      <div v-if="!loggedIn" class="bav-mode-tabs" data-tour="fiat-mode">
        <button
          class="bav-mode"
          :class="{ 'bav-mode-active': mode === 'anon' }"
          @click="mode = 'anon'"
        >
          <Icon name="mdi:flash" /> {{ t('backerView.form.quickBack') }}
        </button>
        <button
          class="bav-mode"
          :class="{ 'bav-mode-active': mode === 'login' }"
          @click="goLogin"
        >
          <Icon name="mdi:account" /> {{ t('backerView.form.haveAccount') }}
        </button>
      </div>
      <div v-else class="bav-mode-banner">
        <Icon name="mdi:check-circle" class="bav-mode-banner-icon" />
        <span>{{ t('backerView.form.loggedInAs') }} <strong>{{ authStore.user?.email }}</strong></span>
        <button class="bav-mode-banner-action" @click="useAnonInstead = !useAnonInstead">
          {{ useAnonInstead ? '← ' + t('backerView.form.useMyAccount') : t('backerView.form.backForSomeoneElse') }}
        </button>
      </div>

      <div v-if="effectivelyAnon" class="bav-field">
        <label class="bav-label">{{ t('backerView.form.yourEmail') }}</label>
        <input
          v-model="email"
          type="email"
          class="nc-input bav-input"
          :placeholder="t('backerView.form.emailPlaceholder')"
          autocomplete="email"
          @blur="emailTouched = true"
        />
        <p v-if="emailError" class="bav-error">{{ emailError }}</p>
        <p v-else class="bav-hint">
          We'll create your account + wallet agent automatically and email a secure login link.
        </p>
      </div>

      <!-- Optional: buyer-supplied account names (PB-1, 2026-05-09).
           Collapsed by default — kept frictionless. Both fields optional. -->
      <details v-if="effectivelyAnon" class="bav-naming">
        <summary class="bav-naming-summary">
          <Icon name="mdi:tag-outline" />
          <span>{{ t('backerView.form.customizeNames') }}</span>
          <span class="bav-naming-optional">optional</span>
        </summary>
        <div class="bav-naming-grid">
          <div class="bav-field">
            <label class="bav-label">{{ t('backerView.form.developerName') }}</label>
            <input
              v-model="customDevName"
              type="text"
              class="nc-input bav-input"
              :maxlength="64"
              :placeholder="t('backerView.form.developerNamePh')"
              autocomplete="organization"
            />
            <p class="bav-hint">
              Your account handle. Defaults to a slug from your email if blank.
            </p>
          </div>
          <div class="bav-field">
            <label class="bav-label">{{ t('backerView.form.walletAgentName') }}</label>
            <input
              v-model="customAgentName"
              type="text"
              class="nc-input bav-input"
              :maxlength="64"
              :placeholder="t('backerView.form.walletAgentNamePh')"
            />
            <p class="bav-hint">
              The name of your first agent. You can rename or replace it later.
            </p>
          </div>
        </div>
      </details>

      <div v-else-if="loggedIn" class="bav-field">
        <label class="bav-label">{{ t('backerView.form.receivingAgent') }}</label>
        <select v-model="selectedAgentDid" class="nc-input bav-input" :aria-label="t('backerView.form.receivingAgent')">
          <option v-if="loadingAgents" value="">{{ t('backerView.form.loadingAgents') }}</option>
          <option v-else-if="agentsFailed && agents.length === 0" value="">{{ t('common.readFailed.text', 'This could not be read just now.') }}</option>
          <option v-else-if="agents.length === 0" value="">{{ t('backerView.form.noAgents') }}</option>
          <option v-for="a in agents" :key="a.did" :value="a.did">
            {{ a.name || truncMid(a.did, 20, 8) }}
          </option>
        </select>
        <ReadFailedNotice v-if="agentsFailed && agents.length === 0 && !loadingAgents" dense :retry="loadAgents" data-testid="bav-agents-failed" />
        <p v-else-if="agents.length === 0 && !loadingAgents" class="bav-error">
          {{ t('backerView.form.needsAgent', { unit: localCurrency }) }}
          <router-link to="/onboarding">{{ t('backerView.form.createOne') }}</router-link>
        </p>
        <p v-else class="bav-hint">
          {{ t('backerView.form.flareHint', { unit: localCurrency }) }}
        </p>
      </div>

      <div class="bav-field">
        <label class="bav-label">{{ t('backerView.form.supportAmount') }}</label>
        <div class="bav-amount-wrap" data-tour="fiat-amount">
          <span class="bav-amount-prefix">€</span>
          <input
            v-model.number="eurAmount"
            type="number"
            step="0.01"
            :min="MIN_EUR"
            :max="MAX_EUR"
            class="nc-input bav-amount-input"
            :aria-label="t('backerView.form.amountAria', 'Amount in euros')"
            @input="onEurInput"
          />
          <span class="bav-amount-suffix">EUR</span>
        </div>
        <div class="bav-quick-amounts" data-tour="fiat-quick">
          <button
            v-for="q in [5, 20, 100]"
            :key="q"
            type="button"
            class="bav-quick"
            :class="{ 'bav-quick-active': Number(eurAmount) === q }"
            @click="eurAmount = q"
          >€{{ q }}</button>
        </div>
        <p v-if="amountError" class="bav-error">{{ amountError }}</p>
      </div>

      <!-- Preview — backer-framed: you pay X, get tier flare + a bonus in the frame's units.
           §FESUITE (the loading sweep; 81's ask for the unit): the amount and the rate wait for the tier table's
           read ("0 AVT" and "0 AVT/€" stood there until it answered), and every unit is the frame's own
           (localCurrency: empty until the frame answers, never another frame's name). -->
      <div class="bav-preview">
        <div class="bav-preview-row">
          <span class="bav-preview-l">{{ t('backerView.form.yourContribution') }}</span>
          <span class="bav-preview-r">€{{ eurFormatted }}</span>
        </div>
        <div class="bav-preview-row">
          <span class="bav-preview-l">{{ t('backerView.form.tier') }}</span>
          <span class="bav-preview-r">
            <span class="bav-tier-pill" :class="`bav-tier-pill-${activeTier}`">
              <Icon :name="activeTierIcon" class="bav-tier-pill-icon" />
              {{ tierDisplayName || tierName }}
            </span>
          </span>
        </div>
        <div class="bav-preview-row bav-preview-emph">
          <span class="bav-preview-l">{{ t('backerView.form.avtBonus', { unit: localCurrency }) }}</span>
          <span class="bav-preview-r">{{ tierConfig ? avtFormatted : '—' }} {{ localCurrency }}</span>
        </div>
        <div class="bav-preview-row bav-preview-meta">
          <span>{{ t('backerView.preview.rate') }}: {{ tierConfig ? rateFormatted : '—' }} {{ localCurrency }}/€</span>
          <span><Icon name="mdi:shield-star-outline" /> {{ t('backerView.preview.flareLine') }}</span>
        </div>
      </div>

      <!-- 2026-05-10 — Optional Founders Wall display personalization
           (Migration 0039 / Option C). All three fields are optional:
              • display_name  — public handle on the wall chip
              • display_country — flag emoji (browser-locale prefilled)
              • show_on_wall  — master opt-out
           Server sanitizes display_name (URL strip + char allowlist + 32-char
           cap). Country is never derived from IP — only from the user's
           browser locale, then user confirms before submit. -->
      <div class="bav-walldisplay">
        <div class="bav-walldisplay-header">
          <h3 class="bav-walldisplay-title">{{ t('backerView.wall.title') }}</h3>
          <p class="bav-walldisplay-sub">{{ t('backerView.wall.sub') }}</p>
        </div>

        <div class="bav-walldisplay-grid">
          <div class="bav-walldisplay-field">
            <label class="bav-walldisplay-label">{{ t('backerView.wall.displayName') }}</label>
            <input
              v-model="displayName"
              type="text"
              maxlength="32"
              class="nc-input bav-walldisplay-input"
              :placeholder="t('backerView.wall.displayNamePh')"
            />
            <p class="bav-walldisplay-hint">{{ t('backerView.wall.displayNameHint') }}</p>
          </div>

          <div class="bav-walldisplay-field">
            <label class="bav-walldisplay-label">{{ t('backerView.wall.country') }}</label>
            <select v-model="displayCountry" class="nc-input bav-walldisplay-select" :aria-label="t('backerView.wall.country')">
              <option value="">— {{ t('backerView.wall.noneOpt') }} —</option>
              <option v-for="c in countriesList" :key="c.code" :value="c.code">
                {{ flagEmoji(c.code) }} &nbsp; {{ c.name }}
              </option>
            </select>
            <p class="bav-walldisplay-hint">{{ t('backerView.wall.countryHint') }}</p>
          </div>
        </div>

        <label class="bav-walldisplay-toggle">
          <input v-model="showOnWall" type="checkbox" class="bav-walldisplay-checkbox" />
          <span class="bav-walldisplay-toggle-text">{{ t('backerView.wall.showOnWall') }}</span>
        </label>

        <!-- Live preview of the wall chip (matches LandingPage + FoundersWall render). -->
        <div class="bav-walldisplay-preview" v-if="showOnWall">
          <span class="bav-walldisplay-preview-label">{{ t('backerView.wall.preview') }}</span>
          <div class="bav-walldisplay-preview-chip">
            <FlareBadge :tier="flarePreviewTier" size="xs" :show-label="false" />
            <span v-if="displayCountry" class="flag-frame"><span class="flag-glyph">{{ flagEmoji(displayCountry) }}</span></span>
            <span v-if="displayName.trim()" class="bav-walldisplay-preview-name">{{ displayName.trim() }}</span>
            <span class="bav-walldisplay-preview-amt">+{{ tierConfig ? Number(avtFormatted.replace(/,/g, '')).toLocaleString(appLocale()) : '—' }} {{ localCurrency }}</span>
            <span class="bav-walldisplay-preview-time">· {{ t('backerView.wall.justNow') }}</span>
          </div>
        </div>
      </div>

      <!-- W1 (2026-05-09) — Required Terms-of-Service consent. The checkbox
           captures both: (a) explicit acceptance of the Terms incl. § 13
           Fiat Purchases, AND (b) the EU § 356(5) BGB digital-content
           carve-out (consent to immediate execution + acknowledgement that
           the 14-day withdrawal right expires upon delivery). The BUY
           button is gated until checked. -->
      <label
        class="bav-tos-row"
        :class="{ 'bav-tos-row-error': tosTouched && !tosAccepted }"
      >
        <input
          type="checkbox"
          v-model="tosAccepted"
          class="bav-tos-checkbox"
          @change="tosTouched = true"
        />
        <span class="bav-tos-text">
          {{ t('backerView.tos.prefix') }}
          <router-link :to="{ name: 'legal', params: { page: 'terms' } }" target="_blank" rel="noopener" class="bav-tos-link">
            {{ t('backerView.tos.termsLink') }}
          </router-link>
          {{ t('backerView.tos.middle') }}
          <router-link :to="{ name: 'legal', params: { page: 'privacy' } }" target="_blank" rel="noopener" class="bav-tos-link">
            {{ t('backerView.tos.privacyLink') }}
          </router-link>.
          {{ t('backerView.tos.suffix', { unit: localCurrency }) }}
        </span>
      </label>

      <button
        class="nc-btn nc-btn-primary bav-buy-btn"
        data-tour="fiat-checkout"
        :disabled="!canSubmit || submitting"
        @click="submit"
      >
        <Icon v-if="submitting" name="mdi:loading" class="bav-spin" />
        <Icon v-else name="mdi:hand-coin-outline" />
        {{ submitting ? t('backerView.openingStripe') : t('backerView.backForEur', { amount: eurFormatted }) }}
      </button>

      <p v-if="serverError" class="bav-error bav-server-error">{{ serverError }}</p>

      <!-- Payment methods strip — slim version inside the form for context. -->
      <PaymentLogos size="sm" :show-label="false" :tight="true" class="bav-payment-strip-inline" />

      <p class="bav-legal" v-html="t('backerView.legal')"></p>
    </section>

    <!-- How it works — assurance + clarity -->
    <section v-if="!onrampDisabled" class="bav-explainer">
      <h2 class="bav-explainer-title">{{ t('backerView.explainer.title') }}</h2>
      <div class="bav-explainer-grid">
        <div class="bav-explainer-step">
          <div class="bav-step-num">1</div>
          <h3>{{ t('backerView.explainer.step1') }}</h3>
          <p>{{ t('backerView.explainer.step1Desc') }}</p>
        </div>
        <div class="bav-explainer-step">
          <div class="bav-step-num">2</div>
          <h3>{{ t('backerView.explainer.step2') }}</h3>
          <p>{{ t('backerView.explainer.step2Desc') }}</p>
        </div>
        <div class="bav-explainer-step">
          <div class="bav-step-num">3</div>
          <h3>{{ t('backerView.explainer.step3', { unit: localCurrency }) }}</h3>
          <p>{{ t('backerView.explainer.step3Desc', { unit: localCurrency }) }}</p>
        </div>
        <div class="bav-explainer-step">
          <div class="bav-step-num">4</div>
          <h3>{{ t('backerView.explainer.step4') }}</h3>
          <p>{{ t('backerView.explainer.step4Desc', { unit: localCurrency }) }}</p>
        </div>
      </div>
    </section>

    <!-- §15 — Progress to Shadow Chancellor (gated reveal).
         ONLY shown to backers with architect/founder/shadow tier — strangers
         never see Shadow mentioned (hidden tier stays hidden). The card
         shows their cumulative spend toward €500 + a 4-tile encirclement
         preview of what they unlock when they cross. Already-Shadow backers
         get a "you've crossed the line" affirmation instead. -->
    <section v-if="shouldShowShadowProgress" class="bav-shadow-progress">
      <div class="bav-shadow-progress-head">
        <div>
          <div class="bav-shadow-eyebrow">{{ t('backerView.explainer.shadowChancellor') }}</div>
          <h2 v-if="!isAlreadyShadow" class="bav-shadow-title">
            {{ t('backerView.shadow.gap', { eur: shadowGapEur.toFixed(0) }) }}
          </h2>
          <h2 v-else class="bav-shadow-title bav-shadow-title-already">
            {{ t('backerView.shadow.alreadyTitle') }}
          </h2>
        </div>
        <div class="bav-shadow-progress-meta">
          <span class="bav-shadow-cumulative">
            €{{ Math.round(flareStatus?.cumulative_eur_qualifying || 0) }}
            <span class="bav-shadow-cumulative-sep">/</span>
            €{{ Math.round(flareStatus?.shadow_threshold_eur || 500) }}
          </span>
        </div>
      </div>

      <!-- Progress bar — fills from cumulative toward threshold. -->
      <div class="bav-shadow-bar">
        <div
          class="bav-shadow-bar-fill"
          :style="{
            width: `${Math.min(100, Math.round(((flareStatus?.cumulative_eur_qualifying || 0) / (flareStatus?.shadow_threshold_eur || 500)) * 100))}%`
          }"
        />
      </div>

      <p class="bav-shadow-explainer">
        <template v-if="!isAlreadyShadow">
          {{ t('backerView.shadow.explainBefore') }}
        </template>
        <template v-else>
          {{ t('backerView.shadow.explainAfter') }}
        </template>
      </p>

      <!-- 19-variant preview gallery — non-interactive, pure preview -->
      <div class="bav-shadow-gallery">
        <div v-for="v in (['sauron','goth','obsidian','void','aurora','phoenix','crystal','blackhole','halloween','inferno','glacier','matrix','galaxy','ink','circuit','yule','sakura','solstice','harvest'] as const)" :key="v" class="bav-shadow-tile">
          <FlareEncirclement
            tier="shadow_chancellor"
            :variant="v"
            initials="??"
            size="lg"
          />
          <span class="bav-shadow-tile-label">{{ v }}</span>
        </div>
      </div>
    </section>

    <!-- Founders Wall CTA -->
    <section class="bav-founders-link">
      <FlareBadge tier="founder" size="md" :show-label="false" />
      <div class="bav-founders-link-text">
        <h3>{{ t('backerView.explainer.wallPublic') }}</h3>
        <p>{{ t('backerView.foundersLink.desc') }}</p>
      </div>
      <router-link to="/founders-wall" class="bav-founders-link-cta">
        {{ t('backerView.foundersLink.cta') }} 
      </router-link>
    </section>

    <!-- FAQ — honest answers to the questions everyone asks -->
    <section class="bav-faq">
      <h2 class="bav-explainer-title">{{ t('backerView.explainer.faqTitle') }}</h2>
      <details v-for="(q, i) in FAQ" :key="i" class="bav-faq-item">
        <summary>
          <Icon name="mdi:chevron-right" class="bav-faq-chev" />
          <span>{{ q.q }}</span>
        </summary>
        <p v-html="q.a"></p>
      </details>
    </section>

    <section v-if="purchases.length" class="bav-history">
      <h2 class="bav-history-title">{{ t('backerView.history.title') }}</h2>
      <table class="bav-history-table">
        <thead>
          <tr>
            <th>{{ t('backerView.history.colDate') }}</th>
            <th>EUR</th>
            <th>{{ localCurrency }}</th>
            <th>{{ t('backerView.history.colStatus') }}</th>
            <th>{{ t('backerView.history.colAgent') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in purchases" :key="p.fiat_purchase_id">
            <td>{{ formatDate(p.created_at) }}</td>
            <td>€{{ p.eur_amount }}</td>
            <td class="bav-mono">{{ p.avt_amount }}</td>
            <td>
              <span class="bav-status-pill" :class="`bav-status-pill-${p.status}`">{{ p.status }}</span>
            </td>
            <td class="bav-mono">{{ p.agent_did ? truncMid(p.agent_did, 12, 6) : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useCurrency } from '@/composables/useCurrency'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  fiatOnrampService,
  type TiersResponse,
  type PublicStatsResponse,
} from '@/services/api/fiatOnramp'
import { developerApi } from '@/services/api/developer'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import { apiClient } from '@/services/api/client'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useAlive } from '@/composables/useAlive'
import PaymentLogos from '@/components/common/PaymentLogos.vue'
import { COUNTRIES, flagEmoji, detectBrowserCountry } from '@/utils/countries'

const router = useRouter()
const authStore = useAuthStore()
const { t } = useI18n()
const { localCurrency } = useCurrency()
// §FEFRAME W2: whether THIS registry sells through the fiat on-ramp is the server's word (registry-config
// `fiat_onramp_enabled`), never "is the unit AVT": that test closed the lane on every frame that exists today and
// would have opened it on any frame that happened to call its unit AVT. (The genesis backend stays authoritative.)
const { config: registryConfig } = useRegistryConfig()
const fiatNotApplicable = computed(() => registryConfig.value.fiat_onramp_enabled !== true)
// 2026-07-31: the operator can close the fiat lane entirely (FIAT_ONRAMP_ENABLED=false).
// The backend then 503s /fiat/tiers and /fiat/checkout-session. Swallowing that and
// rendering an empty purchase form would keep presenting an offer surface for a lane
// that cannot transact, so we say so plainly and hide the purchase UI instead.
// §BAFIN (2026-10-01): the gate also opens from registry-config alone (fiatNotApplicable), so the pitch never
// paints for the moment before /fiat/tiers answers 503 on a registry whose lane is off.
const onrampDisabled = ref(false)

// ── Public stats / live ticker (PB-1 polish, 2026-05-09) ──
// `/fiat/stats/public` returns aggregate counts + last 10 anonymized
// purchases (flare tier + minutes_ago + AVT only — NEVER email/agent).
// We rotate through the recent_backers list every 5s for the ticker, and
// animate the big counter on first load.
const publicStats = ref<PublicStatsResponse | null>(null)
const tickerIdx = ref(0)
let tickerTimer: number | null = null
let statsTimer: number | null = null

const tickerCurrent = computed(() => {
  const list = publicStats.value?.recent_backers || []
  return list.length ? list[tickerIdx.value % list.length] : null
})
const tickerKey = computed(() => `t-${tickerIdx.value}`)

// Animated counters — count up from 0 to actual on first load.
const animBackers = ref(0)
const animAvt = ref(0)
function animateCounter(target: number, ref_: { value: number }, durMs = 1100) {
  const start = ref_.value
  const startTs = performance.now()
  function step(now: number) {
    const t = Math.min(1, (now - startTs) / durMs)
    const eased = 1 - Math.pow(1 - t, 3) // ease-out cubic
    ref_.value = Math.round(start + (target - start) * eased)
    if (t < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

// Trust-strip tooltip explanations (accessible via title attribute).
// Click-to-expand modals deferred to a future polish pass.
const TRUST_TIPS = computed(() => ({
  minting:    `Only the genesis registry can issue ${localCurrency.value}. Federated registries cannot inflate supply — they acquire ${localCurrency.value} only via cross-registry transfer from genesis.`,
  mica:       'Units are closed-loop platform credits: no cash-out, no redemption, no market outside the platform. Euro purchases are switched off. No authority has confirmed a classification.',
  audit:      'Every event lives on the public EventStore ledger. The supply auditor proves total_circulating == tokens_issued − tokens_destroyed every 60 seconds.',
  opensource: 'TheProtocol is open-source under AGPL-3.0. Run your own registry. The federation is permissionless once licensed.',
}))

// FAQ — honest, plain answers. Update freely as questions evolve.
const FAQ = computed<Array<{ q: string; a: string }>>(() => [
  { q: t('backerView.faq.q1', { unit: localCurrency.value }), a: t('backerView.faq.a1', { unit: localCurrency.value }) },
  { q: t('backerView.faq.q2'), a: t('backerView.faq.a2') },
  { q: t('backerView.faq.q3'), a: t('backerView.faq.a3', { unit: localCurrency.value }) },
  { q: t('backerView.faq.q4'), a: t('backerView.faq.a4') },
  { q: t('backerView.faq.q5'), a: t('backerView.faq.a5') },
  { q: t('backerView.faq.q6'), a: t('backerView.faq.a6') },
  { q: t('backerView.faq.q7', { unit: localCurrency.value }), a: t('backerView.faq.a7') },
])

function formatAgo(seconds: number): string {
  if (seconds < 60) return `${seconds}${t('backerView.ago.secs')}`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}${t('backerView.ago.mins')}`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}${t('backerView.ago.hours')}`
  return `${Math.floor(hours / 24)}${t('backerView.ago.days')}`
}

// Map a tier_label to its flare bucket so the FlareBadge on tier cards
// renders the *actual* badge the buyer would earn.
function tierCardFlare(label: string): 'sentinel' | 'architect' | 'founder' {
  if (label === 'tier_3_premium') return 'founder'
  if (label === 'tier_2_value') return 'architect'
  return 'sentinel'
}

// ── Live tier config (loaded from /api/v1/fiat/tiers — DB-driven, versioned) ──
const tierConfig = ref<TiersResponse | null>(null)
const MIN_EUR = computed(() => Number(tierConfig.value?.min_eur || '1'))
const MAX_EUR = computed(() => Number(tierConfig.value?.max_eur || '500'))

// ── Form state ──
const mode = ref<'anon' | 'login'>('anon')
const useAnonInstead = ref(false)
const email = ref('')
const emailTouched = ref(false)
const eurAmount = ref<number | string>(20)
const selectedAgentDid = ref('')
const agents = ref<{ did: string; name?: string }[]>([])
const loadingAgents = ref(false)
// §FESUITE (2026-10-05): a failed agent-list read said "No agents — create one first" and sent a person who has agents to
// create one; the picker says the read failed now, with Try again (a failed refresh keeps the list it showed)
const agentsFailed = ref(false)
const submitting = ref(false)
const serverError = ref('')
const purchases = ref<any[]>([])

// Optional buyer-supplied names for the auto-onboarding flow (PB-1, 2026-05-09).
// Both blank by default — backend falls back to the auto-slug if empty.
const customDevName = ref('')
const customAgentName = ref('')

// W1 (2026-05-09) — explicit Terms-of-Service consent. Required by EU
// distance-contracts § 312g BGB; the wording captures the § 356(5) BGB
// digital-content carve-out (immediate execution + waiver of withdrawal
// right). Pinned to the version the registry currently enforces.
// §LEGALKIT: the served Terms version comes from the registry (one copy, config.py); this is only the seed.
const TOS_VERSION = ref('2.2')
fetch('/api/v1/auth/registration-config', { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).then(c => { if (c && typeof c.tos_version === 'string' && c.tos_version) TOS_VERSION.value = c.tos_version }).catch(() => {})
const tosAccepted = ref(false)
const tosTouched = ref(false)

// 2026-05-10 — Founders Wall display personalization (Migration 0039).
// Browser-locale prefill happens in onMounted below (no IP processing
// server-side; user confirms before submit). All three optional.
const displayName = ref('')
const displayCountry = ref('')
const showOnWall = ref(true)
const countriesList = COUNTRIES
// True when the 100 Founder slots are all claimed. Drives the SOLD-OUT
// treatment on the tier-3 card AND downgrades the live-preview flare to
// Architect so the buyer sees what they'll actually get.
const founderSlotsSoldOut = computed(() => {
  const stats = publicStats.value
  return stats != null && stats.founder_slots_remaining <= 0
})

// Computed: which flare tier the live preview chip should render. Mirrors
// the active tier so the user sees what their chip will actually look like.
// When tier_3 is selected but Founder slots are sold out, the preview shows
// Architect flare to match the actual flare the user would receive.
const flarePreviewTier = computed<'sentinel' | 'architect' | 'founder'>(() => {
  if (activeTier.value === 'tier_3_premium') {
    return founderSlotsSoldOut.value ? 'architect' : 'founder'
  }
  if (activeTier.value === 'tier_2_value') return 'architect'
  return 'sentinel'
})

const loggedIn = computed(() => authStore.isAuthenticated)
const effectivelyAnon = computed(() => !loggedIn.value || useAnonInstead.value)

// §15 — progress-to-Shadow reveal. Only loads for logged-in backers who
// have already crossed €100 single-tier (architect/founder/shadow). The
// backend gates the cumulative_eur fields to those tiers; we mirror the
// gate here so non-qualifying devs never even fire the request. Hidden
// tier stays hidden from strangers.
const flareStatus = ref<{
  flare_tier: string | null
  cumulative_eur_qualifying: number | null
  shadow_threshold_eur: number | null
} | null>(null)

const shouldShowShadowProgress = computed(() => {
  if (!loggedIn.value) return false
  const fs = flareStatus.value
  if (!fs) return false
  if (!fs.flare_tier || !['architect', 'founder', 'shadow_chancellor'].includes(fs.flare_tier)) return false
  return fs.cumulative_eur_qualifying != null && fs.shadow_threshold_eur != null
})

const shadowGapEur = computed(() => {
  const fs = flareStatus.value
  if (!fs?.cumulative_eur_qualifying || !fs.shadow_threshold_eur) return 0
  return Math.max(0, fs.shadow_threshold_eur - fs.cumulative_eur_qualifying)
})

const isAlreadyShadow = computed(() =>
  flareStatus.value?.flare_tier === 'shadow_chancellor'
)

async function loadFlareStatusForGap() {
  if (!authStore.isAuthenticated) return
  try {
    const r = await apiClient.get('/fiat/flare/status')
    flareStatus.value = r.data
  } catch {
    flareStatus.value = null
  }
}

// ── Tier math — driven by live config from /api/v1/fiat/tiers ──
// Backend is the source of truth; helper functions match
// services/stripe_checkout.py:_sorted_tiers_desc + compute_avt_amount.
function sortedTiersDesc() {
  const tiers = tierConfig.value?.tiers || []
  return [...tiers].sort((a, b) => Number(b.floor_eur) - Number(a.floor_eur))
}

function rateForEur(eur: number): number {
  for (const t of sortedTiersDesc()) {
    if (eur >= Number(t.floor_eur)) return Number(t.avt_per_eur)
  }
  return 0
}

function tierLabelFor(eur: number): string {
  for (const t of sortedTiersDesc()) {
    if (eur >= Number(t.floor_eur)) return t.tier_label
  }
  return 'below_minimum'
}

const eurNum = computed(() => Number(eurAmount.value) || 0)
const eurFormatted = computed(() => eurNum.value.toFixed(2))
const avt = computed(() => Math.floor(eurNum.value * rateForEur(eurNum.value)))
const avtFormatted = computed(() =>
  avt.value.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
)
const rateFormatted = computed(() => rateForEur(eurNum.value).toLocaleString(appLocale()))
const activeTier = computed(() => tierLabelFor(eurNum.value))
const tierName = computed(() => {
  const t = (tierConfig.value?.tiers || []).find(x => x.tier_label === activeTier.value)
  if (!t) return ''
  return t.bonus_label ? `${t.bonus_label} BONUS` : 'BASE TIER'
})

// Tier cards rendered from live config.
const tierCards = computed(() =>
  (tierConfig.value?.tiers || []).map(t => ({
    label: t.tier_label,
    rate: Number(t.avt_per_eur).toLocaleString(appLocale()),
    floor: Number(t.floor_eur),
    bonus: t.bonus_label || '',
  })).sort((a, b) => a.floor - b.floor),
)

// Backer-tier presentation layer — maps live tier config to named/iconned tiers.
// Live data (rate, floor, bonus) drives, but display name + icon + tagline +
// suggested commit amount come from this map keyed off tier_label.
//
// Operators can rename in future by extending FiatPricingConfig with display
// fields; for now this is a frontend-only rebrand with sensible defaults.
// Per-tier static (icon + suggestedAmount).
// displayName + tagline now pulled from i18n via TIER_PRESENTATION computed below.
const TIER_PRESENTATION_BASE: Record<string, {
  icon: string
  suggestedAmount: number
  i18nKey: string
}> = {
  tier_1_base:    { icon: 'mdi:shield-half-full', suggestedAmount: 5,   i18nKey: 'sentinel' },
  tier_2_value:   { icon: 'mdi:compass-outline',  suggestedAmount: 25,  i18nKey: 'architect' },
  tier_3_premium: { icon: 'mdi:diamond-stone',    suggestedAmount: 100, i18nKey: 'founder' },
}

const TIER_PRESENTATION = computed<Record<string, {
  displayName: string
  icon: string
  tagline: string
  suggestedAmount: number
}>>(() => {
  const out: Record<string, { displayName: string; icon: string; tagline: string; suggestedAmount: number }> = {}
  for (const [label, base] of Object.entries(TIER_PRESENTATION_BASE)) {
    out[label] = {
      icon: base.icon,
      suggestedAmount: base.suggestedAmount,
      displayName: t(`becomeABackerTiers.${base.i18nKey}.displayName`),
      tagline: t(`becomeABackerTiers.${base.i18nKey}.tagline`),
    }
  }
  return out
})

const backerTiers = computed(() =>
  (tierConfig.value?.tiers || [])
    .map(row => {
      const pres = TIER_PRESENTATION.value[row.tier_label] || {
        displayName: row.tier_label.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        icon: 'mdi:star-outline',
        tagline: '',
        suggestedAmount: Number(row.floor_eur),
      }
      return {
        label: row.tier_label,
        displayName: pres.displayName,
        icon: pres.icon,
        tagline: pres.tagline,
        suggestedAmount: pres.suggestedAmount,
        rate: Number(row.avt_per_eur).toLocaleString(appLocale()),
        floor: Number(row.floor_eur),
        bonus: row.bonus_label || '',
      }
    })
    .sort((a, b) => a.floor - b.floor),
)

const tierDisplayName = computed(() => {
  const pres = TIER_PRESENTATION.value[activeTier.value]
  return pres?.displayName || ''
})

const activeTierIcon = computed(() => {
  const pres = TIER_PRESENTATION.value[activeTier.value]
  return pres?.icon || 'mdi:star-outline'
})

function selectTier(tier: { floor: number }) {
  // Click a tier → set EUR to that tier's FLOOR (cheapest entry for that tier).
  // User can adjust upward via the amount input below. Predictable & honest:
  // clicking "Sentinel" with floor €1 lands on €1, not some artificial suggestion.
  // After setting, scroll the amount input into view so the user immediately
  // sees where to adjust if they want to give more.
  eurAmount.value = tier.floor
  // Defer scroll until DOM updates (computed re-run + Vue patch)
  setTimeout(() => {
    const el = document.querySelector('.bav-amount-input') as HTMLInputElement | null
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.focus({ preventScroll: true })
      el.select?.()
    }
  }, 80)
}

// ── Validation ──
const emailError = computed(() => {
  if (!effectivelyAnon.value || !emailTouched.value) return ''
  if (!email.value.trim()) return 'Email required for the quick-buy flow.'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim())) return 'Enter a valid email.'
  return ''
})

const amountError = computed(() => {
  if (!eurNum.value) return ''
  if (eurNum.value < MIN_EUR.value) return `Minimum is €${MIN_EUR.value}.`
  if (eurNum.value > MAX_EUR.value) return `Maximum is €${MAX_EUR.value}.`
  return ''
})

const canSubmit = computed(() => {
  if (eurNum.value < MIN_EUR.value || eurNum.value > MAX_EUR.value) return false
  if (!tosAccepted.value) return false
  if (effectivelyAnon.value) {
    return !!email.value.trim() && !emailError.value
  }
  return !!selectedAgentDid.value
})

async function loadPublicStats(animate = false) {
  try {
    const stats = await fiatOnrampService.getPublicStats()
    publicStats.value = stats
    const targetBackers = stats.total_backers || 0
    const targetAvt = Number(stats.total_avt_distributed || 0)
    if (animate) {
      animateCounter(targetBackers, animBackers)
      animateCounter(targetAvt, animAvt)
    } else {
      animBackers.value = targetBackers
      animAvt.value = targetAvt
    }
  } catch (e) {
    /* ok — public endpoint, network glitches don't block the page */
  }
}

// ── Lifecycle ──
// §FESUITE (the leave sweep): a page left during its first read starts no timer when it lands (useAlive)
const alive = useAlive()
onMounted(async () => {
  // 2026-05-10 — Browser-locale prefill for the Founders Wall country
  // dropdown. Pure client-side (Intl.Locale.region); never sends IP to the
  // backend. User confirms before submit.
  try {
    const detected = detectBrowserCountry()
    if (detected) displayCountry.value = detected
  } catch { /* non-fatal */ }

  await loadTiers()
  if (!alive()) return
  // Public stats — fire-and-forget so tier cards render fast even if the stats
  // endpoint is slow. Animate the counter on first successful load.
  loadPublicStats(true)
  // Refresh stats every 30s so the page feels alive on the timescale it runs.
  statsTimer = window.setInterval(() => loadPublicStats(false), 30000)
  // Rotate the ticker every 5s through whatever recent_backers we have.
  tickerTimer = window.setInterval(() => {
    if (!publicStats.value?.recent_backers?.length) return
    tickerIdx.value = (tickerIdx.value + 1) % publicStats.value.recent_backers.length
  }, 5000)
  if (loggedIn.value) {
    await loadAgents()
    await loadPurchases()
    // §15 — kick off flare-status fetch for the progress-to-Shadow card.
    // Self-gated: returns early for non-qualifying tiers + silently fails
    // on 401/403 (anonymous flow keeps working).
    loadFlareStatusForGap()
  }
})

onUnmounted(() => {
  if (tickerTimer) clearInterval(tickerTimer)
  if (statsTimer) clearInterval(statsTimer)
})

async function loadTiers() {
  try {
    tierConfig.value = await fiatOnrampService.getTiers()
  } catch (e: any) {
    if (e?.response?.status === 503) {
      onrampDisabled.value = true
    } else {
      console.warn('[BuyAVT] failed to load tier config; will retry when reachable', e)
    }
  }
}

watch(() => authStore.isAuthenticated, async (now) => {
  if (now) {
    await loadAgents()
    await loadPurchases()
  }
})

async function loadAgents() {
  loadingAgents.value = true
  try {
    const list = await developerApi.listMyAgents()
    agents.value = (list || []).map((a: any) => ({
      did: a.agent_did || a.did,
      name: a.name || a.agent_card_name || '',
    })).filter((a: any) => a.did)
    if (agents.value.length && !selectedAgentDid.value) {
      selectedAgentDid.value = agents.value[0].did
    }
    agentsFailed.value = false
  } catch (e) {
    console.warn('[BuyAVT] failed to load agents', e)
    if (!agents.value.length) agentsFailed.value = true
  } finally {
    loadingAgents.value = false
  }
}

async function loadPurchases() {
  try {
    purchases.value = await fiatOnrampService.listMyPurchases(10)
  } catch {
    /* anonymous or list endpoint disabled */
  }
}

// ── Actions ──
function onEurInput() {
  // Clamp to 2 decimal places
  const n = Number(eurAmount.value)
  if (!isNaN(n) && n > 0) {
    eurAmount.value = Math.round(n * 100) / 100
  }
}

function goLogin() {
  router.push({ path: '/login', query: { returnTo: '/become-a-backer' } })
}

function truncMid(s: string, head = 12, tail = 8): string {
  if (!s || s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

async function submit() {
  serverError.value = ''
  tosTouched.value = true
  if (!tosAccepted.value) {
    serverError.value = 'Please confirm acceptance of the Terms of Service before continuing.'
    return
  }
  if (!canSubmit.value) return
  submitting.value = true
  try {
    const payload: any = {
      eur_amount: eurFormatted.value,
      return_path: '/become-a-backer/success',
      cancel_path: '/become-a-backer',
      // 2026-05-10 — Founders Wall display personalization. Server sanitizes
      // display_name; display_country must be a 2-letter ISO code or omitted.
      display_name: displayName.value.trim() || null,
      display_country: (displayCountry.value || '').toUpperCase() || null,
      show_on_wall: showOnWall.value,
      tos_accepted: true,
      tos_version: TOS_VERSION.value,
    }
    if (effectivelyAnon.value) {
      payload.customer_email = email.value.trim()
      // PB-1 onboarding-name capture (2026-05-09). Both optional — backend
      // sanitizes (allowlist) and falls back to auto-slug on empty/collision.
      const dn = customDevName.value.trim()
      const an = customAgentName.value.trim()
      if (dn) payload.developer_name = dn
      if (an) payload.agent_name = an
    } else {
      payload.agent_did = selectedAgentDid.value
    }
    const resp = await fiatOnrampService.createCheckoutSession(payload)
    // Redirect to Stripe-hosted Checkout
    window.location.href = resp.checkout_url
  } catch (e: any) {
    submitting.value = false
    const detail = e?.response?.data?.detail || e?.message || 'Could not open Stripe Checkout.'
    serverError.value = String(detail).slice(0, 300)
  }
}
</script>

<style scoped>
.bav-root {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 20px 80px;
  position: relative;
  z-index: 1;
}

/* ── Hero ────────────────────────────────────────────────── */
.bav-hero {
  text-align: center;
  margin-bottom: 22px;
  padding-top: 16px;
  position: relative;
}
/* Subtle architectural divider lines flanking the hero on wide screens.
   Adds the "premium magazine" feel without competing with the ambient
   background. Theme-aware. */
.bav-hero::before, .bav-hero::after {
  content: "";
  position: absolute;
  top: 50%;
  width: 64px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.45), transparent);
  pointer-events: none;
  display: none;
}
.bav-hero::before { left: -8px; }
.bav-hero::after  { right: -8px; transform: scaleX(-1); }
@media (min-width: 1100px) {
  .bav-hero::before, .bav-hero::after { display: block; }
}
.bav-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 10px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.22);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--nc-primary, #00d2d2);
  margin-bottom: 18px;
}
.bav-chip-dot {
  width: 6px; height: 6px;
  background: var(--nc-primary, #00d2d2);
  border-radius: 50%;
  animation: bav-pulse-dot 2.4s ease-in-out infinite;
}
@keyframes bav-pulse-dot {
  0%, 100% { box-shadow: 0 0 0 0 rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55); }
  50%      { box-shadow: 0 0 0 6px rgba(var(--nc-primary-rgb, 0, 210, 210), 0); }
}
.bav-h1 {
  font-size: clamp(36px, 5vw, 54px);
  font-weight: 600;
  margin: 0 0 16px;
  letter-spacing: -0.030em;
  line-height: 1.05;
  text-wrap: balance;
}
.bav-h1-accent {
  background: linear-gradient(135deg, var(--nc-primary, #00d2d2) 0%, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  font-style: italic;
  font-weight: 500;
}
/* §FLARESHOP (2026-08-16) — the closed-lane gate. Deliberately calm and
   branded: this is a configuration fact about the registry, not an error. */
.bav-gate {
  max-width: 640px;
  margin: 4rem auto;
  text-align: center;
  padding: 2.5rem 1.5rem;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 0.9rem;
  background: rgba(15, 23, 42, 0.35);
}
.bav-gate-emblem { color: rgba(148, 163, 184, 0.55); display: flex; justify-content: center; margin-bottom: 1rem; }
.bav-gate-title { font-size: 1.4rem; font-weight: 600; margin: 0 0 0.75rem; }
.bav-gate-sub { color: var(--nc-text-muted, #94a3b8); font-size: 0.9rem; line-height: 1.6; margin: 0 auto 1.6rem; max-width: 520px; }
.bav-gate-actions { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; }
.bav-gate-cta {
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.6rem 1.1rem; border-radius: 0.45rem; font-size: 0.88rem; font-weight: 600;
  border: 1px solid rgba(167, 139, 250, 0.45); background: rgba(167, 139, 250, 0.12); color: #c4b5fd;
  transition: background 0.15s;
}
.bav-gate-cta:hover { background: rgba(167, 139, 250, 0.2); }
.bav-gate-link { font-size: 0.82rem; color: rgba(var(--nc-primary-rgb), 0.85); }
.bav-gate-link:hover { text-decoration: underline; }
.bav-gate-foot { margin-top: 1.6rem; font-size: 0.72rem; color: rgba(148, 163, 184, 0.6); font-family: var(--nc-font-mono, monospace); }

.bav-fx-notice {
  max-width: 560px;
  margin: 12px auto 0;
  padding: 10px 16px;
  border: 1px solid rgba(255, 157, 60, 0.4);
  border-radius: 10px;
  background: rgba(255, 157, 60, 0.08);
  color: rgba(255, 200, 150, 0.95);
  font-size: 13px;
  line-height: 1.5;
}
.bav-tagline {
  font-size: 16px;
  line-height: 1.6;
  opacity: 0.82;
  max-width: 640px;
  margin: 0 auto 24px;
  text-wrap: balance;
}
.bav-trust-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 20px;
  justify-content: center;
  align-items: center;
  margin: 8px auto 0;
  max-width: 800px;
}
.bav-trust-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  opacity: 0.75;
  letter-spacing: 0.02em;
}
.bav-trust-icon {
  color: var(--nc-primary, #00d2d2);
  font-size: 14px;
}

/* ── Backer tier cards ───────────────────────────────────── */
.bav-tiers-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin: 28px 0 32px;
}
.bav-backer-tier {
  background:
    linear-gradient(180deg,
      rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.40)) 50%);
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14));
  border-radius: 16px;
  padding: 26px 22px 22px;
  position: relative;
  cursor: pointer;
  transition: transform 220ms cubic-bezier(.2,.7,.2,1),
              box-shadow 250ms ease,
              border-color 200ms ease;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  isolation: isolate;
}
/* Ribbon at top — themed accent line that brightens on hover/active. */
.bav-backer-tier::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55) 30%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55) 70%,
    transparent 100%);
  opacity: 0.45;
  transition: opacity 250ms ease;
  z-index: 1;
}
/* Soft top-right radial glow — same angle as the ribbon. */
.bav-backer-tier::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(280px 130px at 100% -10%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14),
    transparent 70%);
  opacity: 0;
  transition: opacity 250ms ease;
  pointer-events: none;
  z-index: 0;
}
.bav-backer-tier:hover {
  transform: translateY(-3px);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.40);
  box-shadow:
    0 18px 42px -18px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.40),
    0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
}
.bav-backer-tier:hover::before { opacity: 1; }
.bav-backer-tier:hover::after  { opacity: 1; }
.bav-backer-tier-active {
  border-color: var(--nc-primary, #00d2d2);
  background:
    linear-gradient(180deg,
      rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.45)) 65%);
  box-shadow:
    0 0 0 1px var(--nc-primary, #00d2d2),
    0 18px 42px -16px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.50),
    inset 0 1px 0 rgba(var(--nc-primary-rgb, 0, 210, 210), 0.30);
  transform: translateY(-2px);
}
.bav-backer-tier-active::before { opacity: 1; height: 3px; }

/* Founder tier — gold premium treatment regardless of theme. */
.bav-backer-tier-3 {
  background:
    linear-gradient(180deg,
      rgba(245, 158, 11, 0.05) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.42)) 55%);
  border-color: rgba(245, 158, 11, 0.22);
}
.bav-backer-tier-3::before {
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(245, 158, 11, 0.65) 30%,
    rgba(252, 211, 77, 0.85) 50%,
    rgba(245, 158, 11, 0.65) 70%,
    transparent 100%);
  opacity: 0.65;
}
.bav-backer-tier-3::after {
  background: radial-gradient(280px 140px at 100% -10%,
    rgba(245, 158, 11, 0.18),
    transparent 70%);
}
.bav-backer-tier-3 .bav-tier-name { color: rgb(252, 211, 77); }
.bav-backer-tier-3:hover {
  border-color: rgba(245, 158, 11, 0.55);
  box-shadow:
    0 20px 48px -18px rgba(245, 158, 11, 0.45),
    0 0 0 1px rgba(245, 158, 11, 0.20);
}
.bav-backer-tier-3.bav-backer-tier-active {
  border-color: rgb(252, 211, 77);
  background:
    linear-gradient(180deg,
      rgba(245, 158, 11, 0.12) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.48)) 65%);
  box-shadow:
    0 0 0 1px rgb(252, 211, 77),
    0 20px 48px -16px rgba(245, 158, 11, 0.55),
    inset 0 1px 0 rgba(252, 211, 77, 0.40);
}
.bav-backer-tier-3.bav-backer-tier-active::before { height: 3px; }

.bav-tier-corner-mark {
  position: absolute;
  top: 12px;
  right: 14px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.05em;
  opacity: 0.30;
}
.bav-tier-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.bav-tier-icon-svg {
  font-size: 24px;
  color: var(--nc-primary, #00d2d2);
}
.bav-tier-name {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
  letter-spacing: -0.01em;
}
.bav-tier-tagline {
  font-size: 12.5px;
  opacity: 0.70;
  margin: 0 0 14px;
  line-height: 1.45;
  min-height: 36px;
}
.bav-tier-amount {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px dashed rgba(255,255,255,0.07);
}
.bav-tier-amount-from {
  font-size: 11px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
}
.bav-tier-amount-eur {
  font-size: 28px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.bav-tier-perks {
  list-style: none;
  margin: 0 0 16px;
  padding: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.bav-tier-perks li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  opacity: 0.85;
  line-height: 1.4;
}
.bav-tier-perks li svg {
  font-size: 15px;
  color: var(--nc-primary, #00d2d2);
  flex-shrink: 0;
}
.bav-tier-perks li strong { font-weight: 600; opacity: 1; }
.bav-tier-cta {
  width: 100%;
  padding: 9px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.30);
  border-radius: 8px;
  color: var(--nc-primary, #00d2d2);
  font-size: 12px;
  letter-spacing: 0.04em;
  font-weight: 500;
  cursor: pointer;
  transition: all 150ms ease;
}
.bav-tier-cta:hover { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18); }
.bav-backer-tier-active .bav-tier-cta {
  background: var(--nc-primary, #00d2d2);
  color: #000;
  font-weight: 600;
}

/* Legacy classes — kept for any leftover references */
.bav-tiers { display: none; }
.bav-tier { display: none; }

.bav-card {
  background:
    linear-gradient(180deg,
      rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04) 0%,
      var(--nc-surface, rgba(0, 0, 0, 0.50)) 60%);
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20));
  border-radius: 16px;
  padding: 28px 24px 22px;
  backdrop-filter: blur(8px);
  max-width: 720px;
  margin: 0 auto 24px;
  position: relative;
  overflow: hidden;
}
/* Same architectural ribbon as the tier cards. */
.bav-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55) 30%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55) 70%,
    transparent 100%);
  opacity: 0.55;
}
.bav-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.bav-card-head h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.bav-card-head-icon {
  font-size: 20px;
  color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  padding: 6px;
  border-radius: 8px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
}
.bav-mode-tabs { display: flex; gap: 8px; margin-bottom: 20px; }
.bav-mode {
  flex: 1;
  padding: 10px;
  background: transparent;
  border: 1px solid var(--nc-border, rgba(255,255,255,0.10));
  border-radius: 8px;
  color: inherit;
  font-size: 13px;
  cursor: pointer;
  transition: all 150ms ease;
}
.bav-mode:hover { border-color: var(--nc-primary, #00d2d2); }
.bav-mode-active {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}
.bav-mode-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 18px;
  font-size: 13px;
}
.bav-mode-banner-icon { color: var(--nc-primary, #00d2d2); }
.bav-mode-banner-action {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--nc-primary, #00d2d2);
  font-size: 12px;
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.bav-field { margin-bottom: 18px; }
.bav-label {
  display: block;
  font-size: 11px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.65;
  margin-bottom: 6px;
}
.bav-input { width: 100%; }
.bav-hint { font-size: 12px; opacity: 0.6; margin: 6px 0 0; }
.bav-error {
  font-size: 12px;
  color: rgb(239, 68, 68);
  margin: 6px 0 0;
}
.bav-server-error { margin-top: 12px; }

.bav-amount-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.bav-amount-prefix {
  position: absolute;
  left: 14px;
  font-size: 16px;
  opacity: 0.75;
  pointer-events: none;
}
.bav-amount-suffix {
  position: absolute;
  right: 14px;
  font-size: 12px;
  opacity: 0.5;
  pointer-events: none;
  letter-spacing: 0.05em;
}
.bav-amount-input {
  padding-left: 28px !important;
  padding-right: 50px !important;
  font-size: 18px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.bav-quick-amounts { display: flex; gap: 6px; margin-top: 8px; }
.bav-quick {
  flex: 1;
  padding: 6px;
  background: transparent;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  color: inherit;
  font-size: 12px;
  cursor: pointer;
}
.bav-quick:hover { border-color: var(--nc-primary, #00d2d2); }
.bav-quick-active {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border-color: var(--nc-primary, #00d2d2);
  color: var(--nc-primary, #00d2d2);
}

.bav-preview {
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border-radius: 10px;
  padding: 14px 18px;
  margin: 18px 0;
}
.bav-preview-row {
  display: flex;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 13px;
}
.bav-preview-emph {
  font-size: 17px;
  padding: 8px 0;
  border-top: 1px dashed rgba(255,255,255,0.10);
  margin-top: 4px;
}
.bav-preview-emph .bav-preview-r {
  color: var(--nc-primary, #00d2d2);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.bav-preview-meta {
  font-size: 11px;
  opacity: 0.65;
  padding-top: 10px;
  border-top: 1px dashed rgba(255,255,255,0.06);
  margin-top: 8px;
}
.bav-tier-pill {
  font-family: ui-monospace, monospace;
  letter-spacing: 0.10em;
  padding: 1px 8px;
  border-radius: 99px;
  background: rgba(255,255,255,0.04);
  font-size: 10px;
}
.bav-tier-pill-tier_2_value, .bav-tier-pill-tier_3_premium {
  background: rgba(16, 185, 129, 0.15);
  color: rgb(16, 185, 129);
}

/* 2026-05-10 — Founders Wall display personalization (Migration 0039 / Option C).
   Optional opt-in fields. Live preview chip mirrors the LandingPage + FoundersWall
   chip render so the user knows exactly what their wall entry will look like. */
.bav-walldisplay {
  margin: 18px 0 6px;
  padding: 16px 16px 14px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(255,255,255,0.018), rgba(255,255,255,0.005));
  border-radius: 10px;
}
.bav-walldisplay-header { margin-bottom: 12px; }
.bav-walldisplay-title {
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin: 0 0 4px; text-transform: uppercase;
}
.bav-walldisplay-sub {
  font-size: 0.72rem; color: rgba(255,255,255,0.5);
  margin: 0; line-height: 1.5;
}
.bav-walldisplay-grid {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: 12px;
  margin-bottom: 10px;
}
@media (max-width: 640px) { .bav-walldisplay-grid { grid-template-columns: 1fr; } }
.bav-walldisplay-field { display: flex; flex-direction: column; gap: 4px; }
.bav-walldisplay-label {
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.08em;
  color: rgba(255,255,255,0.65); text-transform: uppercase;
}
.bav-walldisplay-input,
.bav-walldisplay-select {
  font-size: 0.85rem;
  padding: 8px 10px;
}
.bav-walldisplay-select { font-family: 'IBM Plex Sans', sans-serif; }
.bav-walldisplay-hint {
  font-size: 0.66rem; color: rgba(255,255,255,0.4);
  margin: 2px 0 0; line-height: 1.45;
}
.bav-walldisplay-toggle {
  display: inline-flex; align-items: center; gap: 8px;
  margin-top: 4px;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.78);
  cursor: pointer;
  user-select: none;
}
.bav-walldisplay-checkbox {
  width: 16px; height: 16px;
  accent-color: rgba(var(--nc-primary-rgb), 0.85);
  cursor: pointer;
}
.bav-walldisplay-preview {
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 8px;
  background: rgba(var(--nc-primary-rgb), 0.02);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.bav-walldisplay-preview-label {
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.16em;
  color: rgba(255,255,255,0.4); text-transform: uppercase;
  flex-shrink: 0;
}
.bav-walldisplay-preview-chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 10px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 100px;
  font-size: 0.74rem;
  font-family: 'IBM Plex Mono', 'SF Mono', monospace;
}
.bav-walldisplay-preview-flag {
  font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif;
  font-size: 0.95rem;
  line-height: 1;
}
.bav-walldisplay-preview-name {
  color: rgba(255, 255, 255, 0.92); font-weight: 600;
  font-family: 'IBM Plex Sans', sans-serif;
  letter-spacing: 0.01em;
  max-width: 14ch;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.bav-walldisplay-preview-amt { color: rgba(255, 255, 255, 0.85); font-weight: 600; }
.bav-walldisplay-preview-time { color: rgba(255, 255, 255, 0.42); }

/* W1 — Required Terms-of-Service consent row above BUY. Visible affordance,
   accessible label, theme-aware accent, and a soft red-shift when the user
   tries to submit without checking. */
.bav-tos-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  margin: 14px 0 6px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.02);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
  font-size: 12px;
  line-height: 1.5;
  color: rgba(255,255,255,0.78);
}
.bav-tos-row:hover {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.45);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04);
}
.bav-tos-row-error {
  border-color: rgba(239, 68, 68, 0.55);
  background: rgba(239, 68, 68, 0.06);
}
.bav-tos-row-error:hover {
  border-color: rgba(239, 68, 68, 0.7);
  background: rgba(239, 68, 68, 0.08);
}
.bav-tos-checkbox {
  margin-top: 2px;
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  accent-color: var(--nc-primary, #00d2d2);
  cursor: pointer;
}
.bav-tos-text {
  flex: 1;
  user-select: none;
}
.bav-tos-link {
  color: var(--nc-primary, #00d2d2);
  text-decoration: underline;
  text-underline-offset: 2px;
  font-weight: 500;
}
.bav-tos-link:hover { text-decoration-thickness: 1.5px; }

.bav-buy-btn {
  width: 100%;
  font-size: 14px;
  letter-spacing: 0.06em;
  padding: 16px;
  margin-top: 6px;
  font-weight: 600;
  position: relative;
  overflow: hidden;
}
/* Subtle sheen on hover — only over the button, doesn't bleed. */
.bav-buy-btn:not(:disabled):hover {
  box-shadow:
    0 0 0 1px var(--nc-primary, #00d2d2),
    0 14px 30px -12px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55);
  transform: translateY(-1px);
}
.bav-buy-btn:not(:disabled):active { transform: translateY(0); }
.bav-spin { animation: bav-spin 1s linear infinite; }
@keyframes bav-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.bav-legal {
  font-size: 11px;
  opacity: 0.55;
  margin: 14px 0 0;
  line-height: 1.5;
  text-align: center;
}

.bav-history { margin-top: 36px; }
.bav-history-title {
  font-size: 13px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  opacity: 0.7;
  margin: 0 0 10px;
}
.bav-history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.bav-history-table th, .bav-history-table td {
  text-align: left;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.bav-history-table th {
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
}
.bav-mono {
  font-family: ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}
.bav-status-pill {
  font-size: 10px;
  letter-spacing: 0.05em;
  padding: 1px 8px;
  border-radius: 99px;
  text-transform: uppercase;
}
.bav-status-pill-completed { background: rgba(16, 185, 129, 0.15); color: rgb(16, 185, 129); }
.bav-status-pill-pending { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12); color: var(--nc-primary, #00d2d2); }
.bav-status-pill-failed, .bav-status-pill-refunded { background: rgba(239, 68, 68, 0.12); color: rgb(239, 68, 68); }

/* ── Payment methods strip ─────────────────────────────── */
.bav-payment-methods {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 14px 0 8px;
  padding: 10px 14px;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 10px;
}
.bav-payment-methods-label {
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.50;
  margin-right: 4px;
}
.bav-payment-method {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  opacity: 0.85;
  letter-spacing: 0.02em;
}
.bav-payment-method svg {
  font-size: 16px;
  opacity: 0.85;
  color: var(--nc-primary, #00d2d2);
}

/* ── Tier pill in preview ──────────────────────────────── */
.bav-tier-pill-icon {
  font-size: 13px;
  vertical-align: middle;
  margin-right: 4px;
}

/* ── Explainer / How it works ──────────────────────────── */
.bav-explainer {
  max-width: 1080px;
  margin: 36px auto 0;
}
.bav-explainer-title {
  text-align: center;
  font-size: 13px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.55;
  margin: 0 0 18px;
  font-weight: 500;
}
.bav-explainer-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.bav-explainer-step {
  background: var(--nc-surface, rgba(0, 0, 0, 0.30));
  border: 1px solid var(--nc-border, rgba(255,255,255,0.06));
  border-radius: 10px;
  padding: 18px 16px;
  position: relative;
  transition: border-color 200ms ease;
}
.bav-explainer-step:hover {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
}
.bav-step-num {
  font-family: ui-monospace, monospace;
  font-size: 14px;
  font-weight: 600;
  color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.22);
  border-radius: 8px;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 10px;
}
.bav-explainer-step h3 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 6px;
}
.bav-explainer-step p {
  font-size: 12.5px;
  line-height: 1.5;
  opacity: 0.72;
  margin: 0;
}

/* ── Naming section (collapsible) ──────────────────────── */
.bav-naming {
  margin: -4px 0 18px;
  background: rgba(0, 0, 0, 0.20);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  overflow: hidden;
}
.bav-naming[open] {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04);
}
.bav-naming-summary {
  list-style: none;
  cursor: pointer;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  user-select: none;
  font-weight: 500;
}
.bav-naming-summary::-webkit-details-marker { display: none; }
.bav-naming-summary svg {
  font-size: 16px;
  color: var(--nc-primary, #00d2d2);
  flex-shrink: 0;
}
.bav-naming-optional {
  margin-left: auto;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.50;
  font-weight: 400;
}
.bav-naming-grid {
  padding: 4px 14px 14px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 640px) {
  .bav-naming-grid { grid-template-columns: 1fr; }
}

/* ── Payment logos strip placement ─────────────────────── */
.bav-payment-strip {
  max-width: 720px;
  margin: 0 auto 24px;
}
.bav-payment-strip-inline {
  margin-top: 12px;
  background: transparent;
  border-color: rgba(255, 255, 255, 0.04);
}

/* ── Live counter ──────────────────────────────────────── */
.bav-live-counter {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  margin: 14px auto 6px;
  padding: 6px 16px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
}
.bav-live-num {
  color: var(--nc-primary, #00d2d2);
  font-weight: 600;
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.bav-live-label {
  opacity: 0.65;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-size: 10px;
}
.bav-live-sep { opacity: 0.30; }

/* ── Live ticker ───────────────────────────────────────── */
.bav-ticker {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 12px auto 0;
  padding: 6px 14px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 99px;
  font-size: 12px;
  opacity: 0.85;
}
.bav-ticker-text { line-height: 1; }
.bav-ticker-text strong { color: var(--nc-primary, #00d2d2); font-weight: 600; }
.bav-ticker-time { opacity: 0.50; margin-left: 8px; font-family: ui-monospace, monospace; font-size: 10.5px; }

.bav-ticker-fade-enter-active,
.bav-ticker-fade-leave-active {
  transition: opacity 0.35s ease, transform 0.35s ease;
}
.bav-ticker-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.bav-ticker-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ── Founder scarcity (on tier card 3) ─────────────────── */
/* §15 — Progress-to-Shadow gated reveal. Only renders for architect+ tier.
   Aesthetic mirrors the Shadow Chancellor palette: deep violet→black with
   crimson accents at the bottom edge. */
.bav-shadow-progress {
  margin: 32px auto;
  max-width: 1100px;
  padding: 28px 32px 26px;
  border-radius: 12px;
  background:
    radial-gradient(ellipse 60% 40% at 50% 110%, rgba(127, 29, 29, 0.18) 0%, transparent 70%),
    radial-gradient(ellipse 60% 50% at 30% -10%, rgba(91, 33, 158, 0.14) 0%, transparent 60%),
    linear-gradient(160deg, rgba(15, 8, 28, 0.95) 0%, rgba(0, 0, 0, 0.98) 100%);
  border: 1px solid rgba(167, 139, 250, 0.32);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.45),
    0 0 0 1px rgba(167, 139, 250, 0.08) inset,
    0 0 30px -10px rgba(91, 33, 158, 0.4);
  color: rgba(220, 220, 240, 0.92);
  font-family: 'IBM Plex Mono', monospace;
}
.bav-shadow-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.bav-shadow-eyebrow {
  font-size: 11px;
  letter-spacing: 0.2em;
  color: rgba(220, 38, 38, 0.85);
  text-transform: uppercase;
  margin-bottom: 6px;
}
.bav-shadow-title {
  font-size: clamp(22px, 3.2vw, 32px);
  font-weight: 700;
  letter-spacing: -0.01em;
  color: rgba(255, 255, 255, 0.98);
  margin: 0;
  text-shadow: 0 0 16px rgba(167, 139, 250, 0.32);
}
.bav-shadow-title-already {
  background: linear-gradient(120deg, rgb(196, 181, 253) 0%, rgb(252, 165, 165) 100%);
  -webkit-background-clip: text;
          background-clip: text;
  color: transparent;
}
.bav-shadow-progress-meta {
  text-align: right;
}
.bav-shadow-cumulative {
  font-size: 14px;
  font-weight: 700;
  color: rgba(196, 181, 253, 0.95);
  letter-spacing: 0.05em;
}
.bav-shadow-cumulative-sep {
  color: rgba(255, 255, 255, 0.35);
  margin: 0 4px;
}
.bav-shadow-bar {
  height: 6px;
  width: 100%;
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(91, 33, 158, 0.35);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 14px;
}
.bav-shadow-bar-fill {
  height: 100%;
  background: linear-gradient(90deg,
    rgba(91, 33, 158, 0.85) 0%,
    rgba(167, 139, 250, 0.95) 60%,
    rgba(220, 38, 38, 0.9) 100%);
  box-shadow: 0 0 12px rgba(167, 139, 250, 0.55);
  transition: width 600ms cubic-bezier(.2,.7,.2,1);
}
.bav-shadow-explainer {
  font-size: 12.5px;
  line-height: 1.6;
  color: rgba(200, 200, 220, 0.7);
  margin: 0 0 18px;
  max-width: 740px;
}
.bav-shadow-explainer em {
  color: rgba(220, 220, 240, 0.92);
  font-style: italic;
}
.bav-shadow-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 14px;
  align-items: start;
}
.bav-shadow-tile {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 18px 8px 12px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(167, 139, 250, 0.18);
}
.bav-shadow-tile-label {
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(196, 181, 253, 0.85);
}

@media (max-width: 640px) {
  .bav-shadow-progress { padding: 22px 18px 18px; margin: 24px 14px; }
  .bav-shadow-progress-head { align-items: flex-start; }
  .bav-shadow-progress-meta { text-align: left; }
  .bav-shadow-gallery { grid-template-columns: 1fr 1fr; gap: 10px; }
}

.bav-founder-scarcity {
  margin: 8px 0 14px;
  padding: 10px 12px;
  background: rgba(245, 158, 11, 0.06);
  border: 1px solid rgba(245, 158, 11, 0.20);
  border-radius: 8px;
}
.bav-founder-bar {
  height: 5px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 99px;
  overflow: hidden;
  margin-bottom: 6px;
}
.bav-founder-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.55), rgb(253, 224, 71));
  border-radius: 99px;
  box-shadow: 0 0 6px rgba(253, 224, 71, 0.4);
  transition: width 600ms ease;
}
.bav-founder-text {
  font-size: 11px;
  letter-spacing: 0.04em;
  color: rgb(252, 211, 77);
}
.bav-founder-text strong { font-weight: 600; }
.bav-founder-rem { opacity: 0.65; margin-left: 4px; }
.bav-founder-bar-full .bav-founder-bar-fill {
  background: linear-gradient(90deg, rgb(110, 231, 183) 0%, rgb(52, 211, 153) 100%);
  box-shadow: 0 0 6px rgba(52, 211, 153, 0.45);
}
.bav-founder-soldout {
  color: rgb(110, 231, 183);
}
.bav-founder-soldout .bav-founder-rem { color: rgba(255, 255, 255, 0.55); }

/* Flag-frame "ID stamp" — applied around country-flag emoji wherever it
   appears (landing chip, BuyAVT preview, founders wall row). Subtle 1px
   border + low-opacity backdrop gives the flag visual containment to match
   the cyber/sovereign aesthetic without competing with the FlareBadge. */
.flag-frame {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 16px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.32);
  padding: 0;
  overflow: hidden;
  flex-shrink: 0;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.02),
    0 1px 2px rgba(0, 0, 0, 0.3);
}
.flag-frame > .flag-glyph {
  font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif;
  font-size: 13px;
  line-height: 1;
  display: block;
  filter: saturate(0.92);
  transform: translateY(-0.5px);
}

.bav-tier-flare {
  margin-right: 4px;
}

/* ── Founders Wall link strip ──────────────────────────── */
.bav-founders-link {
  max-width: 1080px;
  margin: 28px auto 0;
  padding: 18px 22px;
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.07), rgba(0, 0, 0, 0.30));
  border: 1px solid rgba(245, 158, 11, 0.25);
  border-radius: 12px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.bav-founders-link-text { flex: 1; min-width: 0; }
.bav-founders-link-text h3 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: rgb(252, 211, 77);
  letter-spacing: -0.01em;
}
.bav-founders-link-text p {
  margin: 0;
  font-size: 12.5px;
  opacity: 0.75;
  line-height: 1.45;
}
.bav-founders-link-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.40);
  border-radius: 8px;
  color: rgb(252, 211, 77);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-decoration: none;
  font-weight: 500;
  white-space: nowrap;
  transition: background 200ms ease, transform 200ms ease;
}
.bav-founders-link-cta:hover {
  background: rgba(245, 158, 11, 0.22);
  transform: translateX(2px);
}

/* ── FAQ ───────────────────────────────────────────────── */
.bav-faq {
  max-width: 720px;
  margin: 36px auto 0;
}
.bav-faq-item {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding: 12px 4px;
}
.bav-faq-item summary {
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  font-weight: 500;
  padding: 6px 0;
  user-select: none;
}
.bav-faq-item summary::-webkit-details-marker { display: none; }
.bav-faq-chev {
  font-size: 18px;
  opacity: 0.55;
  flex-shrink: 0;
  transition: transform 220ms ease;
}
.bav-faq-item[open] .bav-faq-chev { transform: rotate(90deg); opacity: 0.85; }
.bav-faq-item p {
  margin: 8px 0 12px 28px;
  font-size: 13px;
  line-height: 1.6;
  opacity: 0.78;
}
.bav-faq-item p strong {
  color: rgba(255, 255, 255, 0.95);
  font-weight: 600;
}

/* ── Mobile ────────────────────────────────────────────── */
@media (max-width: 1023.98px) {
  .bav-tiers-grid { grid-template-columns: 1fr; max-width: 480px; margin-left: auto; margin-right: auto; }
  .bav-explainer-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .bav-tiers { grid-template-columns: 1fr; }
  .bav-h1 { font-size: 32px; }
  .bav-tagline { font-size: 14px; }
  .bav-explainer-grid { grid-template-columns: 1fr; }
  .bav-trust-strip { gap: 4px 14px; }
  .bav-trust-item { font-size: 11px; }
  .bav-live-counter { flex-wrap: wrap; gap: 4px 6px; padding: 6px 12px; font-size: 11px; }
  .bav-ticker { font-size: 11px; padding: 6px 10px; }
  .bav-founders-link { flex-direction: column; align-items: stretch; text-align: center; gap: 12px; }
  .bav-founders-link-cta { justify-content: center; }
}
</style>
