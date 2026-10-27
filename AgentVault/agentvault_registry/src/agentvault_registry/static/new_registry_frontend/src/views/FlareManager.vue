<template>
  <!--
    FlareManager — PB-1 backer flare control surface (2026-05-09).

    Two layers:
      1. Profile flare card — what the dev earned, permanent
      2. Agent flare card — which agent currently wears the agent flare,
         with a button to move it to any other active agent the dev owns

    Falls back to a "no flare yet — become a backer" CTA if the dev hasn't
    purchased. Cosmetic-only — never moves AVT. Movement is reactive +
    optimistic; on backend success the local list is patched in place.
  -->
  <div class="flm-root nc-page">
    <header class="flm-hero">
      <div class="flm-chip">
        <span class="flm-chip-dot"></span>
        {{ t('flareManagerView.chip') }}
      </div>
      <h1 class="flm-h1">{{ t('flareManagerView.h1a') }}<span class="flm-h1-accent">{{ t('flareManagerView.h1Accent') }}</span></h1>
      <p class="flm-tagline">{{ t('flareManagerView.tagline') }}</p>
    </header>

    <div v-if="loading" class="flm-loading">
      <Icon name="mdi:loading" class="flm-spin" /> {{ t('flareManagerView.loadingFlare') }}
    </div>

    <!-- §FESUITE (the failing-reads census, 2026-10-04): with the profile's read failed this said "No flare yet" -->
    <ReadFailedNotice v-else-if="profileFailed && !profileTier" :retry="loadProfile" />
    <div v-else-if="!profileTier" class="flm-empty">
      <Icon name="mdi:shield-off-outline" class="flm-empty-icon" />
      <h2>{{ t('flareManagerView.empty') }}</h2>
      <p>{{ t('flareManagerView.emptyDescription') }}</p>
      <!-- §BAFIN: the euro door only where the euro lane is on (its route sends a fiat-off registry to /pricing);
           elsewhere the Flare Shop, which sells the same flares in this frame's own unit -->
      <router-link v-if="fiatOn" to="/become-a-backer" class="nc-btn nc-btn-primary flm-empty-cta">
        <Icon name="mdi:hand-coin-outline" /> {{ t('flareManagerView.becomeBacker') }}
      </router-link>
      <router-link v-else to="/flare-shop" class="nc-btn nc-btn-primary flm-empty-cta">
        <Icon name="mdi:store-outline" /> {{ t('nav.items.flareShop') }}
      </router-link>
    </div>

    <template v-else>
      <!-- Profile flare card — what the dev is currently wearing.
           UserAvatar handles dual-slot composition (encirclement + corner)
           so shadow_chancellor backers see their full presence. Shows the
           CURRENT selection state, mirroring what the rest of the app sees. -->
      <section class="flm-card">
        <div class="flm-card-head">
          <Icon name="mdi:account-star" class="flm-card-icon" />
          <h2>{{ t('flareManagerView.sections.profile') }} <span class="flm-card-sub">{{ t('flareManagerView.sections.profileSub') }}</span></h2>
        </div>
        <div class="flm-flare-display">
          <UserAvatar
            :user="authStore.user"
            :avatar-url="customDisplay.logo_url || null"
            :display-name="customDisplay.display_name || authStore.user?.name || authStore.user?.email || null"
            :granted-at="profileGrantedAt"
            size="xl"
          />
          <div class="flm-flare-meta">
            <p class="flm-flare-name">{{ customDisplay.display_name || tierDisplayName(profileTier) }}</p>
            <p class="flm-flare-tier-line">
              <strong>{{ tierDisplayName(profileTier) }} backer</strong>
              <span v-if="profileGrantedAt"> · granted {{ formatDate(profileGrantedAt) }}</span>
            </p>
            <p class="flm-flare-blurb">
              {{ customDisplay.tagline || tierBlurb(profileTier) }}
            </p>
            <p v-if="customDisplay.flare_id" class="flm-flare-id">
               Flare #{{ customDisplay.flare_id.slice(0, 8) }}
            </p>
          </div>
        </div>
      </section>

      <!-- ─── PICK WHICH FLARE YOU WEAR (multi-slot, 2026-05-11 §12) ───
           Two independent slots: corner badge + avatar encirclement.
           Shows ALL unlocked options as cards; clicking commits via
           PATCH /fiat/flare/selection. Live-preview composition above.
           Locked tiers shown as muted with a "not yet earned" hint. -->
      <section v-if="hasMultiSlot" class="flm-card">
        <div class="flm-card-head">
          <Icon name="mdi:gesture-tap-button" class="flm-card-icon" />
          <h2>{{ t('flareManagerView.sections.pick') }} <span class="flm-card-sub">{{ t('flareManagerView.sections.pickSub') }}</span></h2>
        </div>
        <p class="flm-customize-hint">{{ t('flareManagerView.dualHint') }}</p>

        <!-- Live preview of the composed avatar.
             §15.2 (2026-05-13): bind `:variant="effectiveVariant"` so the
             preview tracks the picker selection. Without this, the preview
             defaulted to 'sauron' regardless of which variant the user
             picked — only the corner-pip + tier slot updated. -->
        <div class="flm-slot-preview">
          <span class="flm-slot-preview-label">{{ t('flareManagerView.preview') }}</span>
          <div class="flm-slot-preview-stack">
            <FlareEncirclement
              v-if="flareStatus?.selected_encirclement_flare"
              :key="`preview-${effectiveVariant}-${effectiveOverlay ?? 'none'}`"
              :tier="flareStatus.selected_encirclement_flare"
              :variant="effectiveVariant"
              :overlay="effectiveOverlay"
              :avatar-url="customDisplay.logo_url || null"
              :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
              size="xl"
            />
            <span v-else class="flm-slot-preview-noenc">
              <span class="flm-slot-preview-initials">{{ (authStore.user?.name || authStore.user?.email || '?').slice(0,2).toUpperCase() }}</span>
            </span>
            <FlareBadge
              v-if="flareStatus?.selected_corner_flare"
              :tier="flareStatus.selected_corner_flare"
              size="md"
              :show-label="false"
              :accent-color="customDisplay.accent_color || null"
              class="flm-slot-preview-corner"
            />
          </div>
          <p class="flm-slot-preview-caption">
            <span v-if="flareStatus?.selected_encirclement_flare">{{ t('flareManagerView.previewLine.encirclement', { tier: tierDisplayName(flareStatus.selected_encirclement_flare) }) }}</span>
            <span v-else>{{ t('flareManagerView.previewLine.noEncirclement') }}</span>
            <span class="flm-slot-preview-sep">·</span>
            <span v-if="flareStatus?.selected_corner_flare">{{ t('flareManagerView.previewLine.corner', { tier: tierDisplayName(flareStatus.selected_corner_flare) }) }}</span>
            <span v-else>{{ t('flareManagerView.previewLine.noCorner') }}</span>
          </p>
        </div>

        <!-- Corner slot picker -->
        <h3 class="flm-slot-h3">{{ t('flareManagerView.cornerBadge') }}</h3>
        <div class="flm-slot-grid">
          <button
            v-for="tier in (flareStatus?.unlocked_corner_flares || [])"
            :key="`corner-${tier}`"
            class="flm-slot-card"
            :class="{ 'flm-slot-card--active': flareStatus?.selected_corner_flare === tier }"
            :disabled="slotSaving"
            @click="setCorner(tier)"
          >
            <FlareBadge :tier="tier" size="md" :show-label="false" />
            <span class="flm-slot-card-label">{{ tierDisplayName(tier) }}</span>
            <span v-if="flareStatus?.selected_corner_flare === tier" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
          </button>
          <button
            class="flm-slot-card flm-slot-card--clear"
            :class="{ 'flm-slot-card--active': !flareStatus?.selected_corner_flare }"
            :disabled="slotSaving"
            @click="setCorner(null)"
          >
            <Icon name="mdi:eye-off" class="flm-slot-card-icon-muted" />
            <span class="flm-slot-card-label">{{ t('flareManagerView.hideCorner') }}</span>
            <span v-if="!flareStatus?.selected_corner_flare" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
          </button>
        </div>

        <!-- §20 (2026-05-13) — ADMIN CORNER BADGE PICKER.
             Visible only to admins (is_admin or any admin_* sub-flag) AND
             only when they actually wear a corner badge. Each tile renders
             the chosen variant via FlareBadge with explicit cornerVariant
             override. NULL/"hide" reverts to the default tier icon. -->
        <template v-if="flareStatus?.caller_is_admin && flareStatus?.selected_corner_flare">
          <h3 class="flm-slot-h3 flm-slot-h3-admin">{{ t('flareManagerView.cornerIconAdmin') }}</h3>
          <p class="flm-slot-variant-hint">{{ t('flareManagerView.cornerIconHint') }}</p>
          <div class="flm-variant-grid">
            <button
              class="flm-variant-card flm-variant-card--admin"
              :class="{ 'flm-variant-card--active': !cornerVariantValue }"
              :disabled="slotSaving"
              @click="setCornerVariant(null)"
            >
              <FlareBadge :tier="flareStatus.selected_corner_flare" size="md" :show-label="false" />
              <div class="flm-variant-meta">
                <span class="flm-variant-label">{{ t('flareManagerView.default') }}</span>
                <span class="flm-variant-sub">{{ t('flareManagerView.standardTierIcon') }}</span>
              </div>
              <span v-if="!cornerVariantValue" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
            </button>
            <button
              v-for="cv in (flareStatus?.available_corner_variants || [])"
              :key="`corner-variant-${cv}`"
              class="flm-variant-card flm-variant-card--admin"
              :class="{ 'flm-variant-card--active': cornerVariantValue === cv }"
              :disabled="slotSaving"
              @click="setCornerVariant(cv as CornerVariantId)"
            >
              <FlareBadge
                :tier="flareStatus.selected_corner_flare"
                :corner-variant="cv as CornerVariantId"
                size="md"
                :show-label="false"
              />
              <div class="flm-variant-meta">
                <span class="flm-variant-label">{{ cornerVariantLabel(cv) }}</span>
                <span class="flm-variant-sub">{{ cornerVariantSub(cv) }}</span>
              </div>
              <span v-if="cornerVariantValue === cv" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
              <span v-else class="flm-variant-admin-tag">
                 {{ t('flareManagerView.adminTag') }}
              </span>
            </button>
          </div>
        </template>

        <!-- Encirclement slot picker (only renders if any encirclement is unlocked) -->
        <template v-if="(flareStatus?.unlocked_encirclement_flares || []).length > 0">
          <h3 class="flm-slot-h3 flm-slot-h3-enc">{{ t('flareManagerView.avatarEncirclement') }}</h3>
          <div class="flm-slot-grid">
            <button
              v-for="tier in (flareStatus?.unlocked_encirclement_flares || [])"
              :key="`enc-${tier}`"
              class="flm-slot-card flm-slot-card--enc"
              :class="{ 'flm-slot-card--active': flareStatus?.selected_encirclement_flare === tier }"
              :disabled="slotSaving"
              @click="setEncirclement(tier)"
            >
              <FlareEncirclement
                :tier="tier"
                :variant="effectiveVariant"
                :initials="'??'"
                size="md"
              />
              <span class="flm-slot-card-label">{{ tierDisplayName(tier) }}</span>
              <span v-if="flareStatus?.selected_encirclement_flare === tier" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
            </button>
            <button
              class="flm-slot-card flm-slot-card--clear"
              :class="{ 'flm-slot-card--active': !flareStatus?.selected_encirclement_flare }"
              :disabled="slotSaving"
              @click="setEncirclement(null)"
            >
              <Icon name="mdi:eye-off" class="flm-slot-card-icon-muted" />
              <span class="flm-slot-card-label">{{ t('flareManagerView.hideEncirclement') }}</span>
              <span v-if="!flareStatus?.selected_encirclement_flare" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
            </button>
          </div>

          <!-- §14 — Encirclement variant picker. Visible only to backers
               actively wearing an encirclement (otherwise the choice has no
               visual). Each tile renders the variant via FlareEncirclement
               with explicit `variant` prop (live preview at xl).
               §19 (2026-05-13): picker grid split into 2 sections — EARNED
               (unlocked variants) and COMING SOON (locked cosmetic variants
               awaiting achievement gating). Section heads make the visual
               hierarchy obvious. -->
          <template v-if="flareStatus?.selected_encirclement_flare">
            <h3 class="flm-slot-h3 flm-slot-h3-enc">{{ t('flareManagerView.encirclementStyle') }}</h3>
            <p class="flm-slot-variant-hint">{{ t('flareManagerView.encirclementStyleHint') }}</p>

            <!-- §19: EARNED section — unlocked variants the dev can wear today -->
            <h4 class="flm-variant-section-head flm-variant-section-head--earned">
              <Icon name="mdi:check-circle-outline" class="flm-variant-section-icon" />
              {{ t('flareManagerView.earned') }}
              <span class="flm-variant-section-count">{{ ENCIRCLEMENT_VARIANTS.filter(x => !lockedVariants.has(x.id) && !seasonalVariants.has(x.id)).length }}</span>
              <span class="flm-variant-section-sub">— {{ t('flareManagerView.earnedSub') }}</span>
            </h4>
            <div class="flm-variant-grid">
              <button
                v-for="v in ENCIRCLEMENT_VARIANTS.filter(x => !lockedVariants.has(x.id) && !seasonalVariants.has(x.id))"
                :key="`variant-earned-${v.id}`"
                class="flm-variant-card"
                :class="{
                  'flm-variant-card--active': effectiveVariant === v.id,
                }"
                :disabled="slotSaving"
                @click="setVariant(v.id)"
              >
                <FlareEncirclement
                  :tier="flareStatus.selected_encirclement_flare"
                  :variant="v.id"
                  :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
                  size="xl"
                />
                <div class="flm-variant-meta">
                  <span class="flm-variant-label">{{ v.label }}</span>
                  <span class="flm-variant-sub">{{ v.sub }}</span>
                </div>
                <span v-if="effectiveVariant === v.id" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
              </button>
            </div>

            <!-- §20: SEASONAL section — variants tied to a calendar window.
                 Will be auto-granted via cron during their window in the
                 future. Today they're cosmetic-locked but pickable.
                 In-season variants get a pulse-highlight ring. -->
            <h4
              v-if="ENCIRCLEMENT_VARIANTS.some(x => seasonalVariants.has(x.id))"
              class="flm-variant-section-head flm-variant-section-head--seasonal"
            >
              <Icon name="mdi:weather-partly-cloudy" class="flm-variant-section-icon" />
              {{ t('flareManagerView.seasonal') }}
              <span class="flm-variant-section-count">{{ ENCIRCLEMENT_VARIANTS.filter(x => seasonalVariants.has(x.id)).length }}</span>
              <span
                v-if="activeSeasonalVariants.size"
                class="flm-variant-section-count flm-variant-section-count--in-season"
              >
                <Icon name="mdi:white-balance-sunny" /> {{ t('flareManagerView.activeCount', { n: activeSeasonalVariants.size }) }}
              </span>
              <span class="flm-variant-section-sub">— {{ t('flareManagerView.seasonalSub') }}</span>
            </h4>
            <div
              v-if="ENCIRCLEMENT_VARIANTS.some(x => seasonalVariants.has(x.id))"
              class="flm-variant-grid flm-variant-grid--seasonal"
            >
              <button
                v-for="v in ENCIRCLEMENT_VARIANTS.filter(x => seasonalVariants.has(x.id))"
                :key="`variant-seasonal-${v.id}`"
                class="flm-variant-card flm-variant-card--seasonal"
                :class="{
                  'flm-variant-card--active': effectiveVariant === v.id,
                  'flm-variant-card--in-season': activeSeasonalVariants.has(v.id),
                }"
                :disabled="slotSaving"
                @click="setVariant(v.id)"
              >
                <FlareEncirclement
                  :tier="flareStatus.selected_encirclement_flare"
                  :variant="v.id"
                  :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
                  size="xl"
                />
                <div class="flm-variant-meta">
                  <span class="flm-variant-label">{{ v.label }}</span>
                  <span class="flm-variant-sub">{{ v.sub }}</span>
                </div>
                <span v-if="effectiveVariant === v.id" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
                <span v-else-if="activeSeasonalVariants.has(v.id)" class="flm-variant-in-season-tag">
                  <Icon name="mdi:white-balance-sunny" /> {{ t('flareManagerView.inSeason') }}
                </span>
                <span v-else class="flm-variant-seasonal-tag">
                  <Icon name="mdi:calendar-month-outline" /> {{ t('flareManagerView.seasonalTag') }}
                </span>
              </button>
            </div>

            <!-- §19: COMING SOON section — achievement-locked variants
                 (NOT seasonal). Visual hint that these exist but aren't
                 yet earned. Selection PATCH still allows picking. -->
            <h4
              v-if="ENCIRCLEMENT_VARIANTS.some(x => lockedVariants.has(x.id) && !seasonalVariants.has(x.id))"
              class="flm-variant-section-head flm-variant-section-head--locked"
            >
              <Icon name="mdi:lock-outline" class="flm-variant-section-icon" />
              {{ t('flareManagerView.comingSoon') }}
              <span class="flm-variant-section-count">{{ ENCIRCLEMENT_VARIANTS.filter(x => lockedVariants.has(x.id) && !seasonalVariants.has(x.id)).length }}</span>
              <span class="flm-variant-section-sub">— {{ t('flareManagerView.comingSoonSub') }}</span>
            </h4>
            <div
              v-if="ENCIRCLEMENT_VARIANTS.some(x => lockedVariants.has(x.id) && !seasonalVariants.has(x.id))"
              class="flm-variant-grid flm-variant-grid--locked"
            >
              <button
                v-for="v in ENCIRCLEMENT_VARIANTS.filter(x => lockedVariants.has(x.id) && !seasonalVariants.has(x.id))"
                :key="`variant-locked-${v.id}`"
                class="flm-variant-card flm-variant-card--locked"
                :class="{
                  'flm-variant-card--active': effectiveVariant === v.id,
                }"
                :disabled="slotSaving"
                @click="setVariant(v.id)"
              >
                <FlareEncirclement
                  :tier="flareStatus.selected_encirclement_flare"
                  :variant="v.id"
                  :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
                  size="xl"
                />
                <div class="flm-variant-meta">
                  <span class="flm-variant-label">{{ v.label }}</span>
                  <span class="flm-variant-sub">{{ v.sub }}</span>
                </div>
                <span v-if="effectiveVariant === v.id" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
                <span v-else class="flm-variant-locked-tag">
                   {{ t('flareManagerView.soonTag') }}
                </span>
              </button>
            </div>
          </template>
        </template>

        <!-- §28 (2026-05-13) — BROKEN-MACHINE OVERLAY axis. Sits ON TOP
             of any base variant. Independent picker section between
             encirclement variant and corner sections. -->
        <template v-if="flareStatus?.selected_encirclement_flare">
          <h3 class="flm-slot-h3 flm-slot-h3-enc">{{ t('flareManagerView.overlayHeader') }}</h3>
          <p class="flm-slot-variant-hint">{{ t('flareManagerView.overlayHint') }}</p>
          <div class="flm-variant-grid flm-variant-grid--overlay">
            <!-- "None" tile clears the overlay -->
            <button
              class="flm-variant-card"
              :class="{ 'flm-variant-card--active': effectiveOverlay === null }"
              :disabled="slotSaving"
              @click="pickOverlay(null)"
            >
              <FlareEncirclement
                :key="`overlay-none-${effectiveVariant}`"
                :tier="flareStatus.selected_encirclement_flare"
                :variant="effectiveVariant"
                :overlay="null"
                :avatar-url="customDisplay.logo_url || null"
                :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
                size="lg"
              />
              <div class="flm-variant-meta">
                <span class="flm-variant-label">{{ t('flareManagerView.overlays.none.label') }}</span>
                <span class="flm-variant-sub">{{ t('flareManagerView.overlays.none.sub') }}</span>
              </div>
              <span v-if="effectiveOverlay === null" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
            </button>
            <!-- One tile per overlay. §pass43c (2026-05-19): bump preview
                 size lg→xl so the persistent base + burst events read
                 cleanly during shopping. Hover state adds scale + glow
                 via .flm-ov-preview-wrap so the burst event is visually
                 inviting without a click. -->
            <button
              v-for="o in ENCIRCLEMENT_OVERLAYS"
              :key="`overlay-${o.id}`"
              class="flm-variant-card flm-variant-card--overlay"
              :class="{ 'flm-variant-card--active': effectiveOverlay === o.id }"
              :disabled="slotSaving"
              @click="pickOverlay(o.id)"
            >
              <span class="flm-ov-preview-wrap">
                <FlareEncirclement
                  :key="`overlay-tile-${o.id}-${effectiveVariant}`"
                  :tier="flareStatus.selected_encirclement_flare"
                  :variant="effectiveVariant"
                  :overlay="o.id"
                  :avatar-url="customDisplay.logo_url || null"
                  :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0,2)"
                  size="xl"
                />
              </span>
              <div class="flm-variant-meta">
                <span class="flm-variant-label">{{ o.label }}</span>
                <span class="flm-variant-sub">{{ o.sub }}</span>
              </div>
              <span v-if="effectiveOverlay === o.id" class="flm-slot-card-active-tag">{{ t('flareManagerView.worn') }}</span>
            </button>
          </div>
        </template>

        <p v-if="slotError" class="flm-error">{{ slotError }}</p>
      </section>

      <!-- Customize flare card (Phase E hardening, 2026-05-09) -->
      <section class="flm-card">
        <div class="flm-card-head">
          <Icon name="mdi:palette-outline" class="flm-card-icon" />
          <h2>{{ t('flareManagerView.sections.customize') }} <span class="flm-card-sub">{{ t('flareManagerView.sections.customizeSub') }}</span></h2>
        </div>
        <p class="flm-customize-hint">{{ t('flareManagerView.customizeHint') }}</p>
        <div class="flm-customize-grid">
          <div class="flm-form-group">
            <label class="flm-label">{{ t('flareManagerView.form.displayName') }}</label>
            <input
              v-model="form.display_name"
              type="text"
              class="nc-input"
              :maxlength="80"
              :placeholder="t('flareManagerView.form.displayNamePh')"
            />
          </div>
          <div class="flm-form-group">
            <label class="flm-label">{{ t('flareManagerView.form.cause') }}</label>
            <input
              v-model="form.cause"
              type="text"
              class="nc-input"
              :maxlength="80"
              :placeholder="t('flareManagerView.form.causePh')"
            />
          </div>
          <div class="flm-form-group flm-form-full">
            <label class="flm-label">{{ t('flareManagerView.form.tagline') }}</label>
            <input
              v-model="form.tagline"
              type="text"
              class="nc-input"
              :maxlength="160"
              :placeholder="t('flareManagerView.form.taglinePh')"
            />
          </div>
          <div class="flm-form-group">
            <label class="flm-label">{{ t('flareManagerView.form.logoUrl') }} <span class="flm-label-sub">https://</span></label>
            <input
              v-model="form.logo_url"
              type="url"
              class="nc-input"
              :maxlength="500"
              placeholder="https://your.site/logo.png"
            />
          </div>
          <div class="flm-form-group">
            <label class="flm-label">{{ t('flareManagerView.form.linkUrl') }} <span class="flm-label-sub">https://</span></label>
            <input
              v-model="form.link_url"
              type="url"
              class="nc-input"
              :maxlength="500"
              placeholder="https://your.site"
            />
          </div>
          <div class="flm-form-group flm-form-full">
            <label class="flm-label">
              {{ t('flareManagerView.form.accentColor') }} <span class="flm-label-sub">hex (#RRGGBB)</span>
              <span v-if="isFixedPaletteTier" class="flm-label-locked">— {{ t('flareManagerView.form.lockedForTier') }}</span>
            </label>
            <div class="flm-color-row" :class="{'flm-color-row--locked': isFixedPaletteTier}">
              <input
                v-model="form.accent_color"
                type="text"
                class="nc-input flm-color-input"
                :maxlength="9"
                placeholder="#00d2d2"
                :disabled="isFixedPaletteTier"
              />
              <input
                v-model="form.accent_color"
                type="color"
                class="flm-color-picker"
                :value="form.accent_color || '#00d2d2'"
                :disabled="isFixedPaletteTier"
              />
              <FlareBadge
                :tier="profileTier"
                size="md"
                :show-label="false"
                :accent-color="isFixedPaletteTier ? null : (form.accent_color || null)"
              />
            </div>
            <p v-if="isFixedPaletteTier" class="flm-color-hint">{{ t('flareManagerView.colorLockedHint') }}</p>
          </div>
        </div>
        <div class="flm-customize-actions">
          <button
            class="nc-btn nc-btn-primary"
            :disabled="customSaving || !customDirty"
            @click="saveCustomization"
          >
            <Icon v-if="customSaving" name="mdi:loading" class="flm-spin" />
            <Icon v-else name="mdi:content-save" />
            {{ customSaving ? t('flareManagerView.saving') : t('flareManagerView.saveCustomization') }}
          </button>
          <button
            v-if="customDirty"
            class="nc-btn nc-btn-ghost"
            @click="resetForm"
          >
             {{ t('flareManagerView.discardChanges') }}
          </button>
        </div>
        <p v-if="customError" class="flm-error">{{ customError }}</p>
        <p v-if="customSuccess" class="flm-success">
          <Icon name="mdi:check-circle" /> {{ customSuccess }}
        </p>
      </section>

      <!-- §23 (2026-05-14) — DUAL-SLOT BEARER picker.
           Replaces the single "Agent flare" section with TWO independent
           pickers. Each slot is equip-able to any of the caller's agents
           (same agent can bear both, or different agents can each bear one).
           Server enforces ≤1 bearer per slot per developer. -->
      <section class="flm-card flm-card--bearer">
        <div class="flm-card-head">
          <Icon name="mdi:robot-happy-outline" class="flm-card-icon" />
          <h2>{{ t('flareManagerView.sections.agentBearers') }} <span class="flm-card-sub">{{ t('flareManagerView.sections.agentBearersSub') }}</span></h2>
        </div>

        <p v-if="agentsLoading" class="flm-current-bearer flm-current-empty">
          <Icon name="mdi:loading" class="flm-spin" /> {{ t('flareManagerView.loadingAgents') }}
        </p>

        <div v-if="!agentsLoading && agentsFailed && agents.length === 0" class="flm-no-agents" data-testid="flm-agents-failed">
          <ReadFailedNotice :retry="loadAgents" />
        </div>
        <div v-else-if="!agentsLoading && agents.length === 0" class="flm-no-agents">
          <p>{{ t('flareManagerView.noAgents') }}</p>
          <router-link to="/onboarding" class="nc-btn">
            <Icon name="mdi:rocket-launch" /> {{ t('flareManagerView.createAgent') }}
          </router-link>
        </div>

        <div v-else-if="!agentsLoading" class="flm-bearer-grid">

          <!-- ────────────────────── CORNER SLOT ─────────────────────── -->
          <!-- §pass11 (2026-05-15) — Bearer-first rendering. Each column
               shows ONLY the current bearer (one row). Swap is done via the
               searchable picker popover below — necessary at 160-agent scale
               (previously the column rendered every agent → 480 cells). -->
          <div class="flm-bearer-col">
            <div class="flm-bearer-col-head">
              <span class="flm-bearer-col-eyebrow">{{ t('flareManagerView.bearers.cornerSlot') }}</span>
              <h3 class="flm-bearer-col-title">
                <Icon name="mdi:hexagon-multiple-outline" class="flm-bearer-col-icon" />
                <span>{{ t('flareManagerView.bearers.cornerTitle') }}</span>
              </h3>
              <p class="flm-bearer-col-sub" v-if="!canEquipCorner" v-html="t('flareManagerView.bearers.cornerNoSelected')" />
              <p class="flm-bearer-col-sub" v-else-if="currentCornerBearer" v-html="t('flareManagerView.bearers.cornerCurrentlyOn', { name: escapeHtml(currentCornerBearer.name || truncMid(currentCornerBearer.did, 22, 8)), flare: escapeHtml(tierShortName(flareStatus?.selected_corner_flare)) })" />
              <p class="flm-bearer-col-sub" v-else>
                {{ t('flareManagerView.bearers.cornerNoBearer') }}
              </p>
            </div>

            <ul class="flm-agent-list flm-bearer-list" :class="{ 'flm-bearer-list--disabled': !canEquipCorner }">
              <li
                v-if="currentCornerBearer"
                :key="`c-${currentCornerBearer.did}`"
                class="flm-agent-row flm-agent-row-bearer"
              >
                <UserAvatar
                  :user="{
                    ...currentCornerBearer,
                    selected_corner_flare:       (flareStatus?.selected_corner_flare ?? null),
                    selected_encirclement_flare: currentCornerBearer.bears_encirclement_flare ? (flareStatus?.selected_encirclement_flare ?? null) : null,
                    flare_encirclement_variant:  currentCornerBearer.bears_encirclement_flare ? (flareStatus?.flare_encirclement_variant ?? null) : null,
                  }"
                  :display-name="currentCornerBearer.name || currentCornerBearer.did"
                  size="sm"
                  class="flm-agent-avatar"
                />
                <div class="flm-agent-meta">
                  <p class="flm-agent-name">{{ currentCornerBearer.name || t('flareManagerView.bearers.unnamedAgent') }}</p>
                  <p class="flm-mono flm-agent-did">{{ truncMid(currentCornerBearer.did, 16, 8) }}</p>
                </div>
                <span v-if="canEquipCorner" class="flm-bearer-slot-pill flm-bearer-slot-pill--corner">
                  <span class="flm-bearer-slot-dot"></span>
                  {{ t('flareManagerView.bearers.wearing') }}
                  <button
                    class="flm-bearer-slot-clear"
                    :disabled="equippingSlot !== null"
                    @click.stop="unequipSlotFrom('corner', currentCornerBearer)"
                    :title="t('flareManagerView.bearers.unequipTitle')"
                  >
                    <Icon name="mdi:close" />
                  </button>
                </span>
                <span v-else class="flm-bearer-slot-pill flm-bearer-slot-pill--disabled">
                  <Icon name="mdi:lock-outline" /> {{ t('flareManagerView.bearers.noSlot') }}
                </span>
              </li>
              <li
                v-else-if="canEquipCorner"
                key="c-empty"
                class="flm-agent-row flm-agent-row-empty"
              >
                <span class="flm-agent-avatar-empty">
                  <Icon name="mdi:account-question-outline" />
                </span>
                <div class="flm-agent-meta">
                  <p class="flm-agent-name flm-agent-name-empty">{{ t('flareManagerView.bearers.noOneEquipped') }}</p>
                  <p class="flm-bearer-col-hint">{{ t('flareManagerView.bearers.pickToEquip') }}</p>
                </div>
              </li>
            </ul>

            <div class="flm-bearer-pick-wrap">
              <button
                v-if="canEquipCorner"
                type="button"
                class="nc-btn nc-btn-secondary flm-bearer-pick-btn"
                :disabled="equippingSlot !== null"
                @click.stop="openBearerPicker('corner')"
                :aria-expanded="bearerPickerOpenFor === 'corner'"
                :aria-haspopup="true"
              >
                <Icon name="mdi:account-search-outline" />
                {{ currentCornerBearer ? t('flareManagerView.bearers.changeBearer') : t('flareManagerView.bearers.pickBearer') }}
              </button>
              <div
                v-if="bearerPickerOpenFor === 'corner'"
                class="flm-bearer-picker-popover"
                @click.stop
              >
                <div class="flm-bearer-picker-head">
                  <input
                    ref="bearerPickerSearchEl"
                    v-model="bearerPickerSearch"
                    type="search"
                    class="flm-bearer-picker-search"
                    :placeholder="t('flareManagerView.bearers.pickerSearchPlaceholder')"
                    :aria-label="t('flareManagerView.bearers.pickerSearchPlaceholder')"
                    @keydown.esc="closeBearerPicker"
                  />
                  <button type="button" class="flm-bearer-picker-close" @click="closeBearerPicker" :title="t('flareManagerView.bearers.pickerClose')">
                    <Icon name="mdi:close" />
                  </button>
                </div>
                <div class="flm-bearer-picker-meta">
                  {{ t('flareManagerView.bearers.pickerCount', { shown: bearerPickerFiltered.length, total: agents.length }) }}
                </div>
                <ul class="flm-bearer-picker-list">
                  <li
                    v-for="a in bearerPickerFiltered"
                    :key="`pick-c-${a.did}`"
                    class="flm-bearer-picker-item"
                    :class="{ 'flm-bearer-picker-item--current': a.bears_corner_flare }"
                  >
                    <span class="flm-bearer-picker-init">{{ (a.name || a.did)[0]?.toUpperCase() || '?' }}</span>
                    <div class="flm-bearer-picker-meta-inner">
                      <p class="flm-agent-name">{{ a.name || t('flareManagerView.bearers.unnamedAgent') }}</p>
                      <p class="flm-mono flm-agent-did">{{ truncMid(a.did, 24, 8) }}</p>
                    </div>
                    <button
                      v-if="!a.bears_corner_flare"
                      type="button"
                      class="nc-btn nc-btn-secondary flm-bearer-picker-equip"
                      :disabled="equippingSlot !== null"
                      @click.stop="equipFromPicker('corner', a)"
                    >
                      <Icon v-if="equippingSlot?.slot === 'corner' && equippingSlot?.did === a.did" name="mdi:loading" class="flm-spin" />
                      <Icon v-else name="mdi:hexagon-multiple" />
                      {{ equippingSlot?.slot === 'corner' && equippingSlot?.did === a.did ? t('flareManagerView.bearers.equipping') : t('flareManagerView.bearers.equipHere') }}
                    </button>
                    <span v-else class="flm-bearer-picker-current-pill">
                      <span class="flm-bearer-slot-dot"></span>
                      {{ t('flareManagerView.bearers.wearing') }}
                    </span>
                  </li>
                  <li v-if="bearerPickerFiltered.length === 0" class="flm-bearer-picker-empty">
                    {{ t('flareManagerView.bearers.pickerNoResults') }}
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <!-- ─────────────────── ENCIRCLEMENT SLOT ──────────────────── -->
          <div class="flm-bearer-col">
            <div class="flm-bearer-col-head">
              <span class="flm-bearer-col-eyebrow">{{ t('flareManagerView.bearers.encirclementSlot') }}</span>
              <h3 class="flm-bearer-col-title">
                <Icon name="mdi:atom-variant" class="flm-bearer-col-icon" />
                <span>{{ t('flareManagerView.bearers.encirclementTitle') }}</span>
              </h3>
              <p class="flm-bearer-col-sub" v-if="!canEquipEncirclement" v-html="t('flareManagerView.bearers.encirclementNoSelected')" />
              <p class="flm-bearer-col-sub" v-else-if="currentEncirclementBearer" v-html="t('flareManagerView.bearers.encirclementCurrentlyOn', { name: escapeHtml(currentEncirclementBearer.name || truncMid(currentEncirclementBearer.did, 22, 8)), flare: escapeHtml(tierShortName(flareStatus?.selected_encirclement_flare)) })" />
              <p class="flm-bearer-col-sub" v-else>
                {{ t('flareManagerView.bearers.encirclementNoBearer') }}
              </p>
            </div>

            <ul class="flm-agent-list flm-bearer-list" :class="{ 'flm-bearer-list--disabled': !canEquipEncirclement }">
              <li
                v-if="currentEncirclementBearer"
                :key="`e-${currentEncirclementBearer.did}`"
                class="flm-agent-row flm-agent-row-bearer"
              >
                <UserAvatar
                  :user="{
                    ...currentEncirclementBearer,
                    selected_corner_flare:       currentEncirclementBearer.bears_corner_flare ? (flareStatus?.selected_corner_flare ?? null) : null,
                    selected_encirclement_flare: (flareStatus?.selected_encirclement_flare ?? null),
                    flare_encirclement_variant:  (flareStatus?.flare_encirclement_variant ?? null),
                  }"
                  :display-name="currentEncirclementBearer.name || currentEncirclementBearer.did"
                  size="sm"
                  class="flm-agent-avatar"
                />
                <div class="flm-agent-meta">
                  <p class="flm-agent-name">{{ currentEncirclementBearer.name || t('flareManagerView.bearers.unnamedAgent') }}</p>
                  <p class="flm-mono flm-agent-did">{{ truncMid(currentEncirclementBearer.did, 16, 8) }}</p>
                </div>
                <span v-if="canEquipEncirclement" class="flm-bearer-slot-pill flm-bearer-slot-pill--enc">
                  <span class="flm-bearer-slot-dot"></span>
                  {{ t('flareManagerView.bearers.wearing') }}
                  <button
                    class="flm-bearer-slot-clear"
                    :disabled="equippingSlot !== null"
                    @click.stop="unequipSlotFrom('encirclement', currentEncirclementBearer)"
                    :title="t('flareManagerView.bearers.unequipTitle')"
                  >
                    <Icon name="mdi:close" />
                  </button>
                </span>
                <span v-else class="flm-bearer-slot-pill flm-bearer-slot-pill--disabled">
                  <Icon name="mdi:lock-outline" /> {{ t('flareManagerView.bearers.noSlot') }}
                </span>
              </li>
              <li
                v-else-if="canEquipEncirclement"
                key="e-empty"
                class="flm-agent-row flm-agent-row-empty"
              >
                <span class="flm-agent-avatar-empty">
                  <Icon name="mdi:account-question-outline" />
                </span>
                <div class="flm-agent-meta">
                  <p class="flm-agent-name flm-agent-name-empty">{{ t('flareManagerView.bearers.noOneEquipped') }}</p>
                  <p class="flm-bearer-col-hint">{{ t('flareManagerView.bearers.pickToEquip') }}</p>
                </div>
              </li>
            </ul>

            <div class="flm-bearer-pick-wrap">
              <button
                v-if="canEquipEncirclement"
                type="button"
                class="nc-btn nc-btn-secondary flm-bearer-pick-btn flm-bearer-pick-btn--enc"
                :disabled="equippingSlot !== null"
                @click.stop="openBearerPicker('encirclement')"
                :aria-expanded="bearerPickerOpenFor === 'encirclement'"
                :aria-haspopup="true"
              >
                <Icon name="mdi:account-search-outline" />
                {{ currentEncirclementBearer ? t('flareManagerView.bearers.changeBearer') : t('flareManagerView.bearers.pickBearer') }}
              </button>
              <div
                v-if="bearerPickerOpenFor === 'encirclement'"
                class="flm-bearer-picker-popover"
                @click.stop
              >
                <div class="flm-bearer-picker-head">
                  <input
                    v-model="bearerPickerSearch"
                    type="search"
                    class="flm-bearer-picker-search"
                    :placeholder="t('flareManagerView.bearers.pickerSearchPlaceholder')"
                    :aria-label="t('flareManagerView.bearers.pickerSearchPlaceholder')"
                    @keydown.esc="closeBearerPicker"
                  />
                  <button type="button" class="flm-bearer-picker-close" @click="closeBearerPicker" :title="t('flareManagerView.bearers.pickerClose')">
                    <Icon name="mdi:close" />
                  </button>
                </div>
                <div class="flm-bearer-picker-meta">
                  {{ t('flareManagerView.bearers.pickerCount', { shown: bearerPickerFiltered.length, total: agents.length }) }}
                </div>
                <ul class="flm-bearer-picker-list">
                  <li
                    v-for="a in bearerPickerFiltered"
                    :key="`pick-e-${a.did}`"
                    class="flm-bearer-picker-item"
                    :class="{ 'flm-bearer-picker-item--current': a.bears_encirclement_flare }"
                  >
                    <span class="flm-bearer-picker-init">{{ (a.name || a.did)[0]?.toUpperCase() || '?' }}</span>
                    <div class="flm-bearer-picker-meta-inner">
                      <p class="flm-agent-name">{{ a.name || t('flareManagerView.bearers.unnamedAgent') }}</p>
                      <p class="flm-mono flm-agent-did">{{ truncMid(a.did, 24, 8) }}</p>
                    </div>
                    <button
                      v-if="!a.bears_encirclement_flare"
                      type="button"
                      class="nc-btn nc-btn-secondary flm-bearer-picker-equip"
                      :disabled="equippingSlot !== null"
                      @click.stop="equipFromPicker('encirclement', a)"
                    >
                      <Icon v-if="equippingSlot?.slot === 'encirclement' && equippingSlot?.did === a.did" name="mdi:loading" class="flm-spin" />
                      <Icon v-else name="mdi:atom-variant" />
                      {{ equippingSlot?.slot === 'encirclement' && equippingSlot?.did === a.did ? t('flareManagerView.bearers.equipping') : t('flareManagerView.bearers.equipHere') }}
                    </button>
                    <span v-else class="flm-bearer-picker-current-pill">
                      <span class="flm-bearer-slot-dot"></span>
                      {{ t('flareManagerView.bearers.wearing') }}
                    </span>
                  </li>
                  <li v-if="bearerPickerFiltered.length === 0" class="flm-bearer-picker-empty">
                    {{ t('flareManagerView.bearers.pickerNoResults') }}
                  </li>
                </ul>
              </div>
            </div>
          </div>

          <!-- ─────────────────── §28 OVERLAY SLOT ───────────────────── -->
          <!-- Third rail: only the encirclement-bearer can wear an overlay.
               §pass11 (2026-05-15) — Single bearer row; no per-agent loop. -->
          <div class="flm-bearer-col">
            <div class="flm-bearer-col-head">
              <span class="flm-bearer-col-eyebrow">{{ t('flareManagerView.bearers.overlaySlot') }}</span>
              <h3 class="flm-bearer-col-title">
                <Icon name="mdi:flash-alert-outline" class="flm-bearer-col-icon" />
                <span>{{ t('flareManagerView.bearers.overlayTitle') }}</span>
              </h3>
              <p class="flm-bearer-col-sub">{{ t('flareManagerView.bearers.overlaySub') }}</p>
            </div>

            <ul class="flm-agent-list flm-bearer-list">
              <!-- §2026-06-30: ALWAYS a bearer row (grid layout) so the no-overlay state
                   gets the same clean avatar+meta / full-width status-bar layout as the
                   other slots; --lit just brightens the tint when an overlay is active. -->
              <li
                v-if="currentEncirclementBearer"
                :key="`o-${currentEncirclementBearer.did}`"
                class="flm-agent-row flm-agent-row-bearer"
                :class="{ 'flm-agent-row-bearer--lit': !!currentEncirclementBearer.flare_encirclement_overlay }"
              >
                <UserAvatar
                  :user="{
                    ...currentEncirclementBearer,
                    selected_corner_flare:       currentEncirclementBearer.bears_corner_flare ? (flareStatus?.selected_corner_flare ?? null) : null,
                    selected_encirclement_flare: (flareStatus?.selected_encirclement_flare ?? null),
                    flare_encirclement_variant:  (flareStatus?.flare_encirclement_variant ?? null),
                    flare_encirclement_overlay:  (currentEncirclementBearer.flare_encirclement_overlay ?? null),
                  }"
                  :display-name="currentEncirclementBearer.name || currentEncirclementBearer.did"
                  size="sm"
                  class="flm-agent-avatar"
                />
                <div class="flm-agent-meta">
                  <p class="flm-agent-name">{{ currentEncirclementBearer.name || t('flareManagerView.bearers.unnamedAgent') }}</p>
                  <p class="flm-mono flm-agent-did">{{ truncMid(currentEncirclementBearer.did, 16, 8) }}</p>
                </div>
                <div class="flm-overlay-picker" :class="{ 'flm-overlay-picker--open': overlayPopoverFor === currentEncirclementBearer.did }">
                  <button
                    type="button"
                    class="flm-bearer-slot-pill flm-bearer-slot-pill--enc flm-overlay-pill"
                    :disabled="agentOverlaySaving === currentEncirclementBearer.did"
                    @click.stop="toggleOverlayPopover(currentEncirclementBearer.did)"
                    :aria-expanded="overlayPopoverFor === currentEncirclementBearer.did"
                    :aria-haspopup="true"
                  >
                    <span class="flm-bearer-slot-dot"></span>
                    {{ overlayPillLabel(currentEncirclementBearer.flare_encirclement_overlay) }}
                    <Icon name="mdi:chevron-down" class="flm-overlay-chevron" />
                  </button>
                  <div
                    v-if="overlayPopoverFor === currentEncirclementBearer.did"
                    class="flm-overlay-popover"
                    @click.stop
                  >
                    <button
                      type="button"
                      class="flm-overlay-popover-item"
                      :class="{ 'flm-overlay-popover-item--active': !currentEncirclementBearer.flare_encirclement_overlay }"
                      @click="pickOverlayForAgent(currentEncirclementBearer, null)"
                    >
                      <span class="flm-overlay-popover-dot"></span>
                      {{ t('flareManagerView.bearers.overlayNone') }}
                    </button>
                    <button
                      v-for="o in ENCIRCLEMENT_OVERLAYS"
                      :key="`o-pop-${currentEncirclementBearer.did}-${o.id}`"
                      type="button"
                      class="flm-overlay-popover-item"
                      :class="{ 'flm-overlay-popover-item--active': currentEncirclementBearer.flare_encirclement_overlay === o.id }"
                      @click="pickOverlayForAgent(currentEncirclementBearer, o.id)"
                    >
                      <span class="flm-overlay-popover-dot flm-overlay-popover-dot--on"></span>
                      {{ o.label }}
                    </button>
                  </div>
                </div>
              </li>
              <li
                v-else
                key="o-empty"
                class="flm-agent-row flm-agent-row-empty"
              >
                <span class="flm-agent-avatar-empty">
                  <Icon name="mdi:lock-outline" />
                </span>
                <div class="flm-agent-meta">
                  <p class="flm-agent-name flm-agent-name-empty">{{ t('flareManagerView.bearers.overlayNeedsEncStandalone') }}</p>
                  <p class="flm-bearer-col-hint">{{ t('flareManagerView.bearers.overlayPickEncFirst') }}</p>
                </div>
              </li>
            </ul>
          </div>
        </div>

        <!-- Tip line — for users with both slots equippable -->
        <p
          v-if="!agentsLoading && agents.length > 0 && canEquipCorner && canEquipEncirclement"
          class="flm-bearer-tip"
        >
          <Icon name="mdi:lightbulb-on-outline" />
          {{ t('flareManagerView.bearers.tipBoth') }}
        </p>

        <p v-if="equipError" class="flm-error">{{ equipError }}</p>
        <p v-if="equipSuccess" class="flm-success">
          <Icon name="mdi:check-circle" /> {{ equipSuccess }}
        </p>
        <p v-if="moveError" class="flm-error">{{ moveError }}</p>
        <p v-if="moveSuccess" class="flm-success">
          <Icon name="mdi:check-circle" /> {{ moveSuccess }}
        </p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { escapeHtml } from '@/utils/escapeHtml'
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { fiatOnrampService } from '@/services/api/fiatOnramp'
import { developerApi } from '@/services/api/developer'
import { apiClient } from '@/services/api/client'
import FlareBadge from '@/components/common/FlareBadge.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import { useI18n } from '@/composables/useI18n'
import { loadRegistryConfig } from '@/composables/useRegistryConfig'

const { t } = useI18n()
// §BAFIN: is the euro lane on here? The shared cached config read; false until it answers, the honest default.
const fiatOn = ref(false)
onMounted(async () => {
  try { fiatOn.value = (await loadRegistryConfig())?.fiat_onramp_enabled === true } catch { /* stays false */ }
})
import UserAvatar from '@/components/common/UserAvatar.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const authStore = useAuthStore()

interface AgentRow {
  did: string
  name?: string
  status: string
  flare_tier?: string | null
  flare_granted_at?: string | null
  // §23 (2026-05-14) — dual-slot bearer flags. Each slot is independently
  // equip-able. Same agent can bear both. Per-developer at-most-one-bearer
  // invariant is enforced server-side in /flare/equip/{slot}.
  bears_corner_flare?: boolean
  bears_encirclement_flare?: boolean
  // Per-agent admin corner-badge variant (admin-only). NULL = use dev's.
  flare_corner_variant?: string | null
  // Per-agent encirclement variant (mirrors Developer column, set via
  // PATCH /fiat/flare/agent/{did}/variant on /my-agents). NULL = inherit
  // the dev's currently-selected variant when bearing the slot.
  flare_encirclement_variant?: string | null
}

const agents = ref<AgentRow[]>([])
// §FESUITE (2026-10-05): a failed agent-list read said "You don't have any active agents yet." and offered to create one; it
// says the read failed now, with Try again (a failed refresh keeps the list that was shown)
const agentsFailed = ref(false)
const loading = ref(true)
const agentsLoading = ref(false)
const moving = ref<string | null>(null)
const moveError = ref('')
const moveSuccess = ref('')

// Fresh /developers/me fetch — authStore.user can be stale if a flare was
// granted after login. Always re-verify before rendering profile flare.
interface LiveProfile {
  flare_tier: string | null
  flare_granted_at: string | null
  flare_id: string | null
  flare_display_name: string | null
  flare_tagline: string | null
  flare_logo_url: string | null
  flare_link_url: string | null
  flare_cause: string | null
  flare_accent_color: string | null
}
const liveProfile = ref<LiveProfile | null>(null)

const profileTier = computed(() =>
  liveProfile.value?.flare_tier ?? authStore.user?.flare_tier ?? null,
)
const profileGrantedAt = computed(() =>
  liveProfile.value?.flare_granted_at ?? authStore.user?.flare_granted_at ?? null,
)

// 2026-05-11 §11 — Tiers with fixed palettes (the visual is by design,
// customization would dilute the rarity). Disable the color picker for these
// tiers + show a hint. Mirrors FlareBadge.FIXED_PALETTE_TIERS — keep in sync.
const FIXED_PALETTE_TIERS = new Set(['shadow_chancellor', 'commander'])
const isFixedPaletteTier = computed(() =>
  Boolean(profileTier.value && FIXED_PALETTE_TIERS.has(profileTier.value as string))
)

// 2026-05-11 §12 — Multi-flare slot state. Loaded from /fiat/flare/status.
interface FlareStatus {
  flare_tier: string | null
  flare_id: string | null
  flare_granted_at: string | null
  selected_corner_flare: string | null
  selected_encirclement_flare: string | null
  unlocked_corner_flares: string[]
  unlocked_encirclement_flares: string[]
  flare_display_name: string | null
  flare_tagline: string | null
  flare_logo_url: string | null
  flare_link_url: string | null
  flare_cause: string | null
  flare_accent_color: string | null
  // §14 (2026-05-12) — encirclement aesthetic variant. NULL → server defaults
  // to 'sauron'. §15.3 (2026-05-13) added aurora/phoenix/crystal. §18 added
  // blackhole/halloween. The picker below sets this via PATCH
  // /fiat/flare/selection with body { variant: ... }.
  flare_encirclement_variant:
    | 'sauron' | 'goth' | 'obsidian' | 'void'
    | 'aurora' | 'phoenix' | 'crystal'
    | 'blackhole' | 'halloween'
    | 'inferno' | 'glacier' | 'matrix'
    | 'galaxy' | 'ink' | 'circuit'
    | 'yule' | 'sakura' | 'solstice' | 'harvest'
    | null
  // §15.3 — server-provided list of available variants + locked set so the
  // picker can render with 🔒 badges. Falls back to a static list if absent.
  available_encirclement_variants?: string[]
  locked_encirclement_variants?: string[]
  // §20 (2026-05-13) — SEASONAL categorization. `seasonal_encirclement_variants`
  // is the subset of LOCKED rendered in the dedicated SEASONAL picker section.
  // `active_seasonal_variants` is computed server-side from current UTC month
  // — the picker pulse-highlights variants whose window is open now.
  seasonal_encirclement_variants?: string[]
  active_seasonal_variants?: string[]
  // §20 (2026-05-13) — admin corner badge variant override + admin-only
  // gating signal. `caller_is_admin` lets the FE conditionally render the
  // admin section.
  flare_corner_variant?: string | null
  available_corner_variants?: string[]
  corner_variants_admin_only?: boolean
  caller_is_admin?: boolean
  // §28 (2026-05-13) — Broken-machine OVERLAY axis. Independent of variant.
  flare_encirclement_overlay?: string | null
  available_encirclement_overlays?: string[]
}

// Variant catalogue — labels + one-line descriptions for the picker. Order
// matters: this is also the visual reading order in the grid (most popular
// → most experimental). Keep in sync with backend ENCIRCLEMENT_VARIANTS.
// §15.3 (2026-05-13) added aurora/phoenix/crystal. Phoenix + Crystal are
// gated as "locked" via flareStatus.locked_encirclement_variants — the
// picker renders them with a 🔒 badge but selection is currently allowed
// (lock UX is cosmetic; achievements system not yet wired).
type VariantId =
  | 'sauron' | 'goth' | 'obsidian' | 'void'
  | 'aurora' | 'phoenix' | 'crystal'
  | 'blackhole' | 'halloween'
  | 'inferno' | 'glacier' | 'matrix'
  | 'galaxy' | 'ink' | 'circuit'
  | 'yule' | 'sakura' | 'solstice' | 'harvest'
// §28 (2026-05-13) — glitch / cascade / panic moved to OverlayId (independent axis).

const ENCIRCLEMENT_VARIANTS = computed<Array<{ id: VariantId; label: string; sub: string }>>(() => [
  { id: 'sauron',    label: t('flareManagerView.variants.sauron.label'),    sub: t('flareManagerView.variants.sauron.sub') },
  { id: 'goth',      label: t('flareManagerView.variants.goth.label'),      sub: t('flareManagerView.variants.goth.sub') },
  { id: 'obsidian',  label: t('flareManagerView.variants.obsidian.label'),  sub: t('flareManagerView.variants.obsidian.sub') },
  { id: 'void',      label: t('flareManagerView.variants.void.label'),      sub: t('flareManagerView.variants.void.sub') },
  { id: 'aurora',    label: t('flareManagerView.variants.aurora.label'),    sub: t('flareManagerView.variants.aurora.sub') },
  { id: 'phoenix',   label: t('flareManagerView.variants.phoenix.label'),   sub: t('flareManagerView.variants.phoenix.sub') },
  { id: 'crystal',   label: t('flareManagerView.variants.crystal.label'),   sub: t('flareManagerView.variants.crystal.sub') },
  { id: 'blackhole', label: t('flareManagerView.variants.blackhole.label'), sub: t('flareManagerView.variants.blackhole.sub') },
  { id: 'halloween', label: t('flareManagerView.variants.halloween.label'), sub: t('flareManagerView.variants.halloween.sub') },
  { id: 'inferno',   label: t('flareManagerView.variants.inferno.label'),   sub: t('flareManagerView.variants.inferno.sub') },
  { id: 'glacier',   label: t('flareManagerView.variants.glacier.label'),   sub: t('flareManagerView.variants.glacier.sub') },
  { id: 'matrix',    label: t('flareManagerView.variants.matrix.label'),    sub: t('flareManagerView.variants.matrix.sub') },
  { id: 'galaxy',    label: t('flareManagerView.variants.galaxy.label'),    sub: t('flareManagerView.variants.galaxy.sub') },
  { id: 'ink',       label: t('flareManagerView.variants.ink.label'),       sub: t('flareManagerView.variants.ink.sub') },
  { id: 'circuit',   label: t('flareManagerView.variants.circuit.label'),   sub: t('flareManagerView.variants.circuit.sub') },
  { id: 'yule',      label: t('flareManagerView.variants.yule.label'),      sub: t('flareManagerView.variants.yule.sub') },
  { id: 'sakura',    label: t('flareManagerView.variants.sakura.label'),    sub: t('flareManagerView.variants.sakura.sub') },
  { id: 'solstice',  label: t('flareManagerView.variants.solstice.label'),  sub: t('flareManagerView.variants.solstice.sub') },
  { id: 'harvest',   label: t('flareManagerView.variants.harvest.label'),   sub: t('flareManagerView.variants.harvest.sub') },
])

// §28 (2026-05-13) — Broken-machine OVERLAY axis. Independent of base variant;
// composes ON TOP of any base. §29 ships panic-a/b/c tournament-round designs.
type OverlayId =
  | 'glitch' | 'cascade' | 'panic-a' | 'panic-b' | 'panic-c'
  | 'breach' | 'refract' | 'stutter' | 'bleed' | 'crackle' | 'feedback' | 'spatter' | 'unravel'  // §pass43
const ENCIRCLEMENT_OVERLAYS = computed<Array<{ id: OverlayId; label: string; sub: string }>>(() => [
  { id: 'glitch',  label: t('flareManagerView.overlays.glitch.label'),  sub: t('flareManagerView.overlays.glitch.sub') },
  { id: 'cascade', label: t('flareManagerView.overlays.cascade.label'), sub: t('flareManagerView.overlays.cascade.sub') },
  { id: 'panic-a', label: t('flareManagerView.overlays.panicA.label'),  sub: t('flareManagerView.overlays.panicA.sub') },
  { id: 'panic-b', label: t('flareManagerView.overlays.panicB.label'),  sub: t('flareManagerView.overlays.panicB.sub') },
  { id: 'panic-c', label: t('flareManagerView.overlays.panicC.label'),  sub: t('flareManagerView.overlays.panicC.sub') },
  // §pass43 (2026-05-18) — 8 new broken-machine overlays
  { id: 'breach',   label: t('flareManagerView.overlays.breach.label'),   sub: t('flareManagerView.overlays.breach.sub') },
  { id: 'refract',  label: t('flareManagerView.overlays.refract.label'),  sub: t('flareManagerView.overlays.refract.sub') },
  { id: 'stutter',  label: t('flareManagerView.overlays.stutter.label'),  sub: t('flareManagerView.overlays.stutter.sub') },
  { id: 'bleed',    label: t('flareManagerView.overlays.bleed.label'),    sub: t('flareManagerView.overlays.bleed.sub') },
  { id: 'crackle',  label: t('flareManagerView.overlays.crackle.label'),  sub: t('flareManagerView.overlays.crackle.sub') },
  { id: 'feedback', label: t('flareManagerView.overlays.feedback.label'), sub: t('flareManagerView.overlays.feedback.sub') },
  { id: 'spatter',  label: t('flareManagerView.overlays.spatter.label'),  sub: t('flareManagerView.overlays.spatter.sub') },
  { id: 'unravel',  label: t('flareManagerView.overlays.unravel.label'),  sub: t('flareManagerView.overlays.unravel.sub') },
])

// §20 (2026-05-13) — ADMIN CORNER BADGE VARIANTS
type CornerVariantId = 'rocket' | 'crown' | 'vault' | 'gavel' | 'atom' | 'network'
const CORNER_VARIANT_META: Record<CornerVariantId, { label: string; sub: string }> = {
  rocket:  { label: 'Rocket',  sub: 'Ascent · launch · escape velocity' },
  crown:   { label: 'Crown',   sub: 'Royal · jeweled · sovereign' },
  vault:   { label: 'Vault',   sub: 'Treasury · safe · fiduciary' },
  gavel:   { label: 'Gavel',   sub: 'Enforcement · ruling · sparks' },
  atom:    { label: 'Atom',    sub: 'Orbital · science · primitives' },
  network: { label: 'Network', sub: 'Federation · mesh · connectivity' },
}
function cornerVariantLabel(id: string): string {
  return t(`flareManagerView.cornerVariants.${id}.label`)
}
function cornerVariantSub(id: string): string {
  return t(`flareManagerView.cornerVariants.${id}.sub`)
}
const flareStatus = ref<FlareStatus | null>(null)
const slotSaving = ref(false)
const slotError = ref('')

// Show the multi-slot picker only when the dev has earned at least 2 corner
// options OR any encirclement. A pure-Sentinel dev has nothing meaningful to
// pick; the section auto-hides for them.
const hasMultiSlot = computed(() => {
  if (!flareStatus.value) return false
  const c = flareStatus.value.unlocked_corner_flares?.length || 0
  const e = flareStatus.value.unlocked_encirclement_flares?.length || 0
  return c >= 2 || e >= 1
})

// Server-truth customization (read by FlareBadge above, also baseline for
// the form's "discard changes" reset.)
const customDisplay = computed(() => ({
  flare_id: liveProfile.value?.flare_id ?? authStore.user?.flare_id ?? null,
  display_name: liveProfile.value?.flare_display_name ?? authStore.user?.flare_display_name ?? null,
  tagline: liveProfile.value?.flare_tagline ?? authStore.user?.flare_tagline ?? null,
  logo_url: liveProfile.value?.flare_logo_url ?? authStore.user?.flare_logo_url ?? null,
  link_url: liveProfile.value?.flare_link_url ?? authStore.user?.flare_link_url ?? null,
  cause: liveProfile.value?.flare_cause ?? authStore.user?.flare_cause ?? null,
  accent_color: liveProfile.value?.flare_accent_color ?? authStore.user?.flare_accent_color ?? null,
}))

// Editable form mirrors customDisplay; user "saves" to PATCH it.
const form = ref({
  display_name: '',
  tagline: '',
  logo_url: '',
  link_url: '',
  cause: '',
  accent_color: '',
})
const customSaving = ref(false)
const customError = ref('')
const customSuccess = ref('')

function syncFormFromServer() {
  form.value.display_name = customDisplay.value.display_name || ''
  form.value.tagline      = customDisplay.value.tagline || ''
  form.value.logo_url     = customDisplay.value.logo_url || ''
  form.value.link_url     = customDisplay.value.link_url || ''
  form.value.cause        = customDisplay.value.cause || ''
  form.value.accent_color = customDisplay.value.accent_color || ''
}

const customDirty = computed(() => {
  return (
    form.value.display_name !== (customDisplay.value.display_name || '') ||
    form.value.tagline      !== (customDisplay.value.tagline || '')      ||
    form.value.logo_url     !== (customDisplay.value.logo_url || '')     ||
    form.value.link_url     !== (customDisplay.value.link_url || '')     ||
    form.value.cause        !== (customDisplay.value.cause || '')        ||
    form.value.accent_color !== (customDisplay.value.accent_color || '')
  )
})

function resetForm() {
  syncFormFromServer()
  customError.value = ''
  customSuccess.value = ''
}

async function saveCustomization() {
  customError.value = ''
  customSuccess.value = ''
  customSaving.value = true
  try {
    // Build payload: only send fields that changed. Use "__clear__" sentinel
    // when the user blanked out a previously-set value.
    const payload: Record<string, string> = {}
    const fields: Array<keyof typeof form.value> = [
      'display_name', 'tagline', 'logo_url', 'link_url', 'cause', 'accent_color',
    ]
    const serverMap: Record<string, string | null> = {
      display_name: customDisplay.value.display_name,
      tagline: customDisplay.value.tagline,
      logo_url: customDisplay.value.logo_url,
      link_url: customDisplay.value.link_url,
      cause: customDisplay.value.cause,
      accent_color: customDisplay.value.accent_color,
    }
    for (const f of fields) {
      const local = (form.value[f] || '').trim()
      const server = serverMap[f] || ''
      if (local === server) continue
      payload[f] = local || '__clear__'
    }
    if (Object.keys(payload).length === 0) {
      customSuccess.value = 'No changes to save.'
      return
    }
    const updated = await fiatOnrampService.customizeFlare(payload)
    // Patch liveProfile with the server's authoritative response.
    if (liveProfile.value) {
      liveProfile.value = {
        ...liveProfile.value,
        flare_id: updated.flare_id ?? liveProfile.value.flare_id,
        flare_display_name: updated.display_name ?? null,
        flare_tagline: updated.tagline ?? null,
        flare_logo_url: updated.logo_url ?? null,
        flare_link_url: updated.link_url ?? null,
        flare_cause: updated.cause ?? null,
        flare_accent_color: updated.accent_color ?? null,
      }
    }
    syncFormFromServer()
    customSuccess.value = 'Flare customization saved.'
  } catch (e: any) {
    customError.value = e?.response?.data?.detail || e?.message || 'Could not save customization.'
  } finally {
    customSaving.value = false
  }
}

const currentBearer = computed(() => agents.value.find(a => !!a.flare_tier))

// §23 (2026-05-14) — Dual-slot bearer computeds. Each slot is independent
// of the other. Same agent can bear both. The renderer respects the per-slot
// flags; the legacy `currentBearer` computed above is kept for compatibility
// with the "any flare-related state" detection elsewhere on the page.
const currentCornerBearer       = computed(() => agents.value.find(a => !!a.bears_corner_flare))
const currentEncirclementBearer = computed(() => agents.value.find(a => !!a.bears_encirclement_flare))

// Slot availability — only show a bearer picker for slots the dev has earned
// AND has selected (selected_*_flare). If they've hidden a slot via the
// "Hide" picker above, there's nothing meaningful to equip.
const canEquipCorner = computed(() => Boolean(
  flareStatus.value?.selected_corner_flare &&
  (flareStatus.value.unlocked_corner_flares || []).includes(flareStatus.value.selected_corner_flare as any)
))
const canEquipEncirclement = computed(() => Boolean(
  flareStatus.value?.selected_encirclement_flare &&
  (flareStatus.value.unlocked_encirclement_flares || []).includes(flareStatus.value.selected_encirclement_flare as any)
))

// Friendly slot tier labels
function tierShortName(tier: string | null | undefined): string {
  if (!tier) return ''
  if (tier === 'shadow_chancellor') return 'Shadow'
  return tier[0].toUpperCase() + tier.slice(1)
}

// Slot-level equip / unequip actions. Server enforces single-bearer-per-slot.
const equippingSlot = ref<{ slot: 'corner' | 'encirclement'; did: string } | null>(null)
const equipError = ref<string>('')
const equipSuccess = ref<string>('')

// §pass11 (2026-05-15) — Bearer picker popover state. With 160+ agents the
// previous per-column v-for over `agents` exploded the render tree (rows ×
// 3 columns) to nearly 500 cells. Now each column shows the bearer only;
// the picker popover serves the swap UX with a searchable list.
const bearerPickerOpenFor = ref<'corner' | 'encirclement' | null>(null)
const bearerPickerSearch = ref<string>('')
const bearerPickerSearchEl = ref<HTMLInputElement | null>(null)

const bearerPickerFiltered = computed<AgentRow[]>(() => {
  const q = bearerPickerSearch.value.trim().toLowerCase()
  if (!q) return agents.value
  return agents.value.filter(a => {
    const hay = `${a.name || ''} ${a.did || ''}`.toLowerCase()
    return hay.includes(q)
  })
})

function openBearerPicker(slot: 'corner' | 'encirclement') {
  bearerPickerOpenFor.value = slot
  bearerPickerSearch.value = ''
  // Autofocus search input next tick. We hold a single ref shared between
  // the two columns — the popover that just opened is the one rendered.
  setTimeout(() => bearerPickerSearchEl.value?.focus(), 0)
}

function closeBearerPicker() {
  bearerPickerOpenFor.value = null
  bearerPickerSearch.value = ''
}

async function equipFromPicker(slot: 'corner' | 'encirclement', target: AgentRow) {
  // Close picker immediately for snappy UX; underlying equip is fire-and-await.
  // We keep the popover OPEN here so the user sees the loading spinner on
  // the row — closing happens after equipSlotOn resolves.
  await equipSlotOn(slot, target)
  if (!equipError.value) {
    closeBearerPicker()
  }
}

// Outside-click handler for the bearer picker popover.
function onWindowClickForBearerPicker(e: MouseEvent) {
  if (!bearerPickerOpenFor.value) return
  const t = e.target as HTMLElement
  if (!t) return
  if (t.closest('.flm-bearer-picker-popover') || t.closest('.flm-bearer-pick-btn')) return
  closeBearerPicker()
}
if (typeof window !== 'undefined') {
  window.addEventListener('click', onWindowClickForBearerPicker)
}
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('click', onWindowClickForBearerPicker)
  }
})

async function equipSlotOn(slot: 'corner' | 'encirclement', target: AgentRow) {
  if (equippingSlot.value) return
  equipError.value = ''
  equipSuccess.value = ''
  equippingSlot.value = { slot, did: target.did }
  try {
    const r = await apiClient.post(`/fiat/flare/equip/${slot}/${encodeURIComponent(target.did)}`)
    const data = r.data || {}
    // Patch local state — clear slot from others, set on target.
    agents.value = agents.value.map(a => {
      if (a.did === target.did) {
        return {
          ...a,
          bears_corner_flare:       slot === 'corner'       ? true : (a.bears_corner_flare ?? false),
          bears_encirclement_flare: slot === 'encirclement' ? true : (a.bears_encirclement_flare ?? false),
          flare_tier: a.flare_tier || (flareStatus.value?.flare_tier ?? null),
        }
      }
      if (slot === 'corner' && a.bears_corner_flare) {
        return { ...a, bears_corner_flare: false }
      }
      if (slot === 'encirclement' && a.bears_encirclement_flare) {
        return { ...a, bears_encirclement_flare: false }
      }
      return a
    })
    const label = slot === 'corner' ? 'Corner badge' : 'Encirclement'
    equipSuccess.value = `${label} equipped on ${target.name || truncMid(target.did, 18, 8)}.`
  } catch (e: any) {
    equipError.value = e?.response?.data?.detail || e?.message || `Failed to equip ${slot}.`
  } finally {
    equippingSlot.value = null
  }
}

async function unequipSlotFrom(slot: 'corner' | 'encirclement', target: AgentRow) {
  if (equippingSlot.value) return
  equipError.value = ''
  equipSuccess.value = ''
  equippingSlot.value = { slot, did: target.did }
  try {
    await apiClient.post(`/fiat/flare/unequip/${slot}/${encodeURIComponent(target.did)}`)
    agents.value = agents.value.map(a => {
      if (a.did !== target.did) return a
      const next = { ...a }
      if (slot === 'corner') next.bears_corner_flare = false
      else next.bears_encirclement_flare = false
      // If both off → clear legacy flare_tier so list views deconverge cleanly.
      if (!next.bears_corner_flare && !next.bears_encirclement_flare) {
        next.flare_tier = null
        next.flare_granted_at = null
      }
      return next
    })
    const label = slot === 'corner' ? 'Corner badge' : 'Encirclement'
    equipSuccess.value = `${label} removed from ${target.name || truncMid(target.did, 18, 8)}.`
  } catch (e: any) {
    equipError.value = e?.response?.data?.detail || e?.message || `Failed to unequip ${slot}.`
  } finally {
    equippingSlot.value = null
  }
}

function tierDisplayName(tier: string | null): string {
  return ({ sentinel: 'Sentinel', architect: 'Architect', founder: 'Founder' } as Record<string, string>)[tier || ''] || ''
}
function tierBlurb(tier: string | null): string {
  return ({
    sentinel:  'Stand watch over the network\'s first chapter.',
    architect: 'Help shape the open-source agent economy.',
    founder:   'A first-class voice in the network\'s genesis.',
  } as Record<string, string>)[tier || ''] || ''
}

function truncMid(s: string, head = 14, tail = 8): string {
  if (!s || s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString(appLocale(), { year: 'numeric', month: 'long', day: 'numeric' })
  } catch { return iso }
}

const profileFailed = ref(false)
async function loadProfile() {
  // Profile fetch is FAST (single row). Resolve `loading` as soon as this
  // returns so the user sees their flare badge + customize panel immediately,
  // without waiting on the agent list (which can be slow for large fleets).
  try {
    const r = await apiClient.get('/developers/me')
    const me = r.data
    if (me) {
      liveProfile.value = {
        flare_tier: me.flare_tier || null,
        flare_granted_at: me.flare_granted_at || null,
        flare_id: me.flare_id || null,
        flare_display_name: me.flare_display_name || null,
        flare_tagline: me.flare_tagline || null,
        flare_logo_url: me.flare_logo_url || null,
        flare_link_url: me.flare_link_url || null,
        flare_cause: me.flare_cause || null,
        flare_accent_color: me.flare_accent_color || null,
      }
      syncFormFromServer()
    }
    profileFailed.value = false
  } catch (e: any) {
    moveError.value = `Could not load profile: ${e?.message || 'unknown error'}`
    profileFailed.value = !liveProfile.value
  } finally {
    loading.value = false
  }
}

async function loadAgents() {
  // Slower path — /developers/me/agents can be heavy for large fleets. Run
  // in the background after `loading` already resolved on profile-only.
  agentsLoading.value = true
  try {
    let list: any[]
    try {
      list = await developerApi.listMyAgents()
    } catch {
      if (!agents.value.length) agentsFailed.value = true
      return
    }
    agentsFailed.value = false
    const all = (list || []).map((a: any) => ({
      did: a.agent_did || a.did,
      name: a.name || a.agent_card_name || '',
      status: a.status || 'active',
      flare_tier: a.flare_tier || null,
      flare_granted_at: a.flare_granted_at || null,
      bears_corner_flare: !!a.bears_corner_flare,
      bears_encirclement_flare: !!a.bears_encirclement_flare,
      flare_corner_variant: a.flare_corner_variant || null,
      flare_encirclement_variant: a.flare_encirclement_variant || null,
    })).filter((a: AgentRow) => !!a.did && a.status === 'active')
    // Surface flare-bearer first, then everything else, capped at 200.
    const sorted = [...all].sort((a, b) => {
      if (a.flare_tier && !b.flare_tier) return -1
      if (!a.flare_tier && b.flare_tier) return 1
      return 0
    })
    agents.value = sorted.slice(0, 200)
  } finally {
    agentsLoading.value = false
  }
}

async function moveTo(target: AgentRow) {
  moveError.value = ''
  moveSuccess.value = ''
  moving.value = target.did
  try {
    const r = await fiatOnrampService.moveAgentFlare(target.did)
    // Patch local state — clear old bearer, set new
    agents.value = agents.value.map(a => {
      if (a.did === r.moved_to_did) return { ...a, flare_tier: r.flare_tier, flare_granted_at: r.flare_granted_at }
      if (r.moved_from_did && a.did === r.moved_from_did) return { ...a, flare_tier: null, flare_granted_at: null }
      return a
    })
    moveSuccess.value = `Flare moved to ${target.name || truncMid(target.did, 18, 8)}.`
  } catch (e: any) {
    moveError.value = e?.response?.data?.detail || e?.message || 'Failed to move flare.'
  } finally {
    moving.value = null
  }
}

// ─── 2026-05-11 §12: multi-flare slot picker ─────────────────────────
async function loadFlareStatus() {
  try {
    const r = await apiClient.get('/fiat/flare/status')
    flareStatus.value = r.data as FlareStatus
    // §14 — also sync auth store so other surfaces (header, sidebar,
    // AgentSwitcher) get the latest selection even before the user
    // logs in fresh. Idempotent — sync of identical values is a no-op.
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    // 401 (no auth) or 403 (no flare yet) → just leave empty; the multi-slot
    // section is hasMultiSlot-gated so it won't render anyway.
    flareStatus.value = null
  }
}

/**
 * Sync the auth store's user object with the slot fields from a flare-status
 * response. Required because header/sidebar/settings/AgentSwitcher all read
 * `authStore.user.*` for avatar composition — without this propagation,
 * those surfaces stay stale after a PATCH (the FlareManager picker updates
 * but everything else still shows the previous variant). §14 fix.
 */
function _syncAuthStoreFromStatus(status: FlareStatus) {
  if (!authStore.user) return
  // Mutate via Pinia's reactive proxy — the user object is reactive, so
  // assigning sub-fields propagates to all consumers (header, sidebar,
  // settings, AgentSwitcher) without a route reload.
  ;(authStore.user as any).selected_corner_flare = status.selected_corner_flare ?? null
  ;(authStore.user as any).selected_encirclement_flare = status.selected_encirclement_flare ?? null
  ;(authStore.user as any).flare_encirclement_variant = status.flare_encirclement_variant ?? null
  // §20 (2026-05-13) — sync admin corner badge variant too so header/sidebar
  // FlareBadge re-renders with the new icon immediately on PATCH.
  ;(authStore.user as any).flare_corner_variant = status.flare_corner_variant ?? null
  // §28 (2026-05-13) — sync overlay so header/sidebar avatars re-render with
  // the picked broken-machine overlay immediately, no reload required.
  ;(authStore.user as any).flare_encirclement_overlay = status.flare_encirclement_overlay ?? null
}

async function setCorner(tier: string | null) {
  if (slotSaving.value) return
  slotSaving.value = true
  slotError.value = ''
  try {
    const body: { corner: string | null } = { corner: tier ?? '__clear__' as any }
    const r = await apiClient.patch('/fiat/flare/selection', body)
    flareStatus.value = r.data as FlareStatus
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    slotError.value = e?.response?.data?.detail || 'Could not switch corner.'
  } finally {
    slotSaving.value = false
  }
}

async function setEncirclement(tier: string | null) {
  if (slotSaving.value) return
  slotSaving.value = true
  slotError.value = ''
  try {
    const body: { encirclement: string | null } = { encirclement: tier ?? '__clear__' as any }
    const r = await apiClient.patch('/fiat/flare/selection', body)
    flareStatus.value = r.data as FlareStatus
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    slotError.value = e?.response?.data?.detail || 'Could not switch encirclement.'
  } finally {
    slotSaving.value = false
  }
}

// §14 (2026-05-12) — switch the encirclement aesthetic variant. Tier stays
// fixed; only the visual flavor changes. Reuses the same PATCH endpoint
// with a `variant` field. Server enforces the value is in
// ENCIRCLEMENT_VARIANTS; 400 on unknown. §15.3 added 3 more variants.
async function setVariant(variant: VariantId) {
  if (slotSaving.value) return
  slotSaving.value = true
  slotError.value = ''
  try {
    const r = await apiClient.patch('/fiat/flare/selection', { variant })
    flareStatus.value = r.data as FlareStatus
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    slotError.value = e?.response?.data?.detail || 'Could not switch variant.'
  } finally {
    slotSaving.value = false
  }
}

// Effective variant — server value with default fallback. Drives the
// "WORN" tag on the picker tiles. §15.3: covers all 7 variant IDs.
const effectiveVariant = computed<VariantId>(() => {
  return (flareStatus.value?.flare_encirclement_variant as VariantId) || 'sauron'
})

// §28 (2026-05-13) — Broken-machine OVERLAY. NULL = no overlay.
const effectiveOverlay = computed<OverlayId | null>(() => {
  const v = flareStatus.value?.flare_encirclement_overlay as OverlayId | null | undefined
  return v ?? null
})

// §28 (2026-05-13) — Per-agent overlay setter, used by the third rail in
// the dual/triple-slot bearer section. Local state mirrors the agents
// list so the picker updates without a refetch.
const agentOverlaySaving = ref<string | null>(null)
async function onAgentOverlayChange(agent: any, value: string) {
  if (agentOverlaySaving.value) return
  const overlay = value === '' ? null : value
  if ((agent.flare_encirclement_overlay || null) === overlay) return
  agentOverlaySaving.value = agent.did
  try {
    const r = await apiClient.patch(
      `/fiat/flare/agent/${encodeURIComponent(agent.did)}/overlay`,
      { overlay: overlay === null ? '__clear__' : overlay },
    )
    agent.flare_encirclement_overlay = r.data?.flare_encirclement_overlay ?? overlay
  } catch (e: any) {
    console.error('[FlareManager] onAgentOverlayChange:', e?.response?.data?.detail || e?.message)
  } finally {
    agentOverlaySaving.value = null
  }
}

// §pass9 (2026-05-15) — Triple-rail alignment popover.
// Each agent's overlay rail shows a "WEARING · <name>" pill identical to
// slot 2's WEARING pill. Click opens a popover listing None + 5 overlays.
const overlayPopoverFor = ref<string | null>(null)
function toggleOverlayPopover(did: string) {
  overlayPopoverFor.value = overlayPopoverFor.value === did ? null : did
}
async function pickOverlayForAgent(agent: any, overlay: string | null) {
  await onAgentOverlayChange(agent, overlay ?? '')
  overlayPopoverFor.value = null
}
function overlayPillLabel(overlay: string | null | undefined): string {
  if (!overlay) return t('flareManagerView.bearers.overlayWearingNone')
  // Use the same label the picker tile shows — keeps copy consistent.
  const o = ENCIRCLEMENT_OVERLAYS.value.find(x => x.id === overlay)
  const name = o?.label || overlay
  return t('flareManagerView.bearers.overlayWearing', { name })
}
// Close popover on outside click. Uses a single document listener while open.
onMounted(() => {
  document.addEventListener('click', _closeOverlayPopoverOnOutside)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', _closeOverlayPopoverOnOutside)
})
function _closeOverlayPopoverOnOutside(_e: MouseEvent) {
  if (overlayPopoverFor.value) overlayPopoverFor.value = null
}

async function pickOverlay(overlay: OverlayId | null) {
  if (slotSaving.value) return
  slotSaving.value = true
  slotError.value = ''
  try {
    const r = await apiClient.patch('/fiat/flare/selection', {
      overlay: overlay === null ? '__clear__' : overlay,
    })
    flareStatus.value = r.data as FlareStatus
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    slotError.value = e?.response?.data?.detail || 'Could not switch overlay.'
  } finally {
    slotSaving.value = false
  }
}

// §20 (2026-05-13) — admin corner badge variant. Server value or null.
// Drives the "WORN" tag on the corner-variant tiles in FlareManager.
const cornerVariantValue = computed<CornerVariantId | null>(() => {
  const v = flareStatus.value?.flare_corner_variant
  if (!v) return null
  return v as CornerVariantId
})

// §20 — switch the admin corner badge variant. NULL clears (reverts to
// default tier icon). Backend enforces admin-only gating + value validation.
async function setCornerVariant(cv: CornerVariantId | null) {
  if (slotSaving.value) return
  slotSaving.value = true
  slotError.value = ''
  try {
    const r = await apiClient.patch('/fiat/flare/selection', {
      corner_variant: cv === null ? '__clear__' : cv,
    })
    flareStatus.value = r.data as FlareStatus
    _syncAuthStoreFromStatus(flareStatus.value)
  } catch (e: any) {
    slotError.value = e?.response?.data?.detail || 'Could not switch corner icon.'
  } finally {
    slotSaving.value = false
  }
}

// §15.3: locked-variant set from server (empty fallback). Used to render
// 🔒 badge + tooltip on locked tiles.
// §20 (2026-05-13) — SEASONAL subset of LOCKED; rendered in dedicated SEASONAL
// section in the picker (between EARNED and COMING SOON). The set comes from
// the server so the frontend doesn't have to duplicate the list.
const seasonalVariants = computed<Set<string>>(() => {
  return new Set(flareStatus.value?.seasonal_encirclement_variants || [])
})
// §20 — currently-active seasonal variants based on server's UTC month
// computation. Used to render a pulse-highlight ring around the in-season tile.
const activeSeasonalVariants = computed<Set<string>>(() => {
  return new Set(flareStatus.value?.active_seasonal_variants || [])
})

const lockedVariants = computed<Set<string>>(() => {
  return new Set(flareStatus.value?.locked_encirclement_variants || [])
})

onMounted(() => {
  // Profile resolves first (fast), then everything else fills in async.
  loadProfile().then(() => {
    loadAgents()
    loadFlareStatus()
  })
})
</script>

<style scoped>
.flm-root {
  max-width: 880px;
  margin: 0 auto;
  padding: 24px 20px 80px;
  position: relative;
  z-index: 1;
}

.flm-hero { text-align: center; margin-bottom: 28px; }
.flm-chip {
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
  margin-bottom: 16px;
}
.flm-chip-dot {
  width: 6px; height: 6px;
  background: var(--nc-primary, #00d2d2);
  border-radius: 50%;
  animation: flm-pulse-dot 2.4s ease-in-out infinite;
}
@keyframes flm-pulse-dot {
  0%, 100% { box-shadow: 0 0 0 0 rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55); }
  50%      { box-shadow: 0 0 0 6px rgba(var(--nc-primary-rgb, 0, 210, 210), 0); }
}
.flm-h1 {
  font-size: 36px;
  font-weight: 600;
  margin: 0 0 12px;
  letter-spacing: -0.02em;
}
.flm-h1-accent {
  background: linear-gradient(135deg, var(--nc-primary, #00d2d2), rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  font-style: italic;
  font-weight: 500;
}
.flm-tagline {
  font-size: 14px;
  opacity: 0.78;
  max-width: 560px;
  margin: 0 auto;
  line-height: 1.55;
}

.flm-loading, .flm-empty {
  text-align: center;
  padding: 40px 20px;
  font-size: 14px;
  opacity: 0.78;
}
.flm-loading .flm-spin {
  display: inline-block;
  width: 18px;
  height: 18px;
  vertical-align: middle;
  margin-right: 6px;
}
.flm-loading .flm-spin :deep(svg) { width: 18px; height: 18px; display: block; }
.flm-empty-icon { font-size: 48px; opacity: 0.4; margin-bottom: 12px; }
.flm-empty h2 { font-size: 20px; margin: 0 0 8px; font-weight: 600; }
.flm-empty p { font-size: 14px; opacity: 0.75; max-width: 460px; margin: 0 auto 18px; line-height: 1.55; }
.flm-empty-cta { display: inline-flex; align-items: center; gap: 8px; }

.flm-card {
  background: var(--nc-surface, rgba(0, 0, 0, 0.45));
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18));
  border-radius: 14px;
  padding: 22px 22px 20px;
  margin-bottom: 18px;
  backdrop-filter: blur(6px);
}
.flm-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.flm-card-icon {
  font-size: 20px;
  color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  padding: 6px;
  border-radius: 8px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
}
.flm-card-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.flm-card-sub {
  font-weight: 400;
  font-size: 13px;
  opacity: 0.55;
}

.flm-flare-display {
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 18px 20px;
  background: rgba(0, 0, 0, 0.30);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  border-radius: 10px;
}
.flm-flare-meta { flex: 1; min-width: 0; }
.flm-flare-name { margin: 0 0 4px; font-size: 18px; font-weight: 600; letter-spacing: -0.01em; }
.flm-flare-when { margin: 0 0 6px; font-size: 12px; opacity: 0.65; }
.flm-flare-blurb { margin: 0; font-size: 13px; opacity: 0.78; line-height: 1.5; }
.flm-flare-id {
  margin: 8px 0 0;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.55;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* Customize panel */
.flm-customize-hint {
  font-size: 12.5px;
  opacity: 0.72;
  line-height: 1.55;
  margin: 0 0 14px;
}
.flm-customize-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 14px;
}
.flm-form-group { display: flex; flex-direction: column; gap: 4px; }
.flm-form-full { grid-column: 1 / -1; }
.flm-label {
  font-size: 11px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  opacity: 0.65;
}
.flm-label-sub {
  margin-left: 6px;
  text-transform: none;
  letter-spacing: normal;
  opacity: 0.55;
  font-family: ui-monospace, monospace;
}
.flm-color-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.flm-color-input { flex: 1; min-width: 100px; max-width: 200px; }
.flm-color-picker {
  width: 38px;
  height: 38px;
  padding: 0;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
}
.flm-color-picker::-webkit-color-swatch-wrapper { padding: 4px; }
.flm-color-picker::-webkit-color-swatch { border: none; border-radius: 4px; }
.flm-color-picker:disabled { cursor: not-allowed; opacity: 0.4; }
.flm-color-row--locked .flm-color-input { opacity: 0.5; cursor: not-allowed; }
.flm-label-locked {
  font-size: 11px; font-style: italic; color: var(--muted); margin-left: 6px;
}
.flm-color-hint {
  font-size: 11px; color: var(--muted); font-style: italic;
  margin: 6px 0 0; line-height: 1.5;
}
.flm-customize-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 14px;
}
.flm-customize-actions .nc-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
@media (max-width: 640px) {
  .flm-customize-grid { grid-template-columns: 1fr; }
}

.flm-current-bearer {
  font-size: 13px;
  opacity: 0.85;
  margin: 0 0 14px;
  padding: 10px 14px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.15);
  border-radius: 8px;
}
.flm-current-empty {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}
.flm-current-bearer .flm-spin {
  display: inline-block;
  width: 14px;
  height: 14px;
  vertical-align: middle;
  margin-right: 4px;
}
.flm-current-bearer .flm-spin :deep(svg) { width: 14px; height: 14px; display: block; }
.flm-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}

.flm-no-agents {
  text-align: center;
  padding: 24px 16px;
  opacity: 0.78;
  font-size: 13px;
}

.flm-agent-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.flm-agent-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: rgba(0, 0, 0, 0.20);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  transition: border-color 200ms ease, background 200ms ease;
}
.flm-agent-row:hover { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20); }
/* §2026-06-30 (Commander "unwhack the bearers") — the bearer row was a flex
   avatar|meta|pill; in a ~250px column the long agent name + DID had NO ellipsis
   so they wrapped to 2-3 lines and the DID painted UNDER the status pill (overlap).
   Reworked to a 2-row GRID: avatar+meta on top (full column width, single-line
   ellipsis), status pill on its own full-width bar below → zero cramping, zero overlap. */
.flm-agent-row-bearer {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "avatar meta"
    "status status";
  column-gap: 12px;
  row-gap: 11px;
  align-items: center;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
}
.flm-agent-row-bearer .flm-agent-avatar { grid-area: avatar; }
.flm-agent-row-bearer .flm-agent-meta   { grid-area: meta; }
.flm-agent-row-bearer .flm-bearer-slot-pill {
  grid-area: status;
  width: 100%;
  box-sizing: border-box;
  justify-content: flex-start;
}
.flm-agent-row-bearer .flm-bearer-slot-clear { margin-left: auto; }  /* ✕ to the far right of the bar */
/* SLOT 3 overlay picker: its status control is a .flm-overlay-picker wrapper (not a bare
   pill) — place it in the same full-width status row, with the chevron pushed to the end. */
.flm-agent-row-bearer .flm-overlay-picker { grid-area: status; width: 100%; }
.flm-agent-row-bearer .flm-overlay-picker .flm-overlay-pill {
  width: 100%;
  box-sizing: border-box;
  justify-content: flex-start;
}
.flm-agent-row-bearer .flm-overlay-pill .flm-overlay-chevron { margin-left: auto; }
.flm-agent-row-bearer--lit { background: rgba(167, 139, 250, 0.09); }
/* name + DID: never wrap, clip with ellipsis so they can't collide with the pill */
.flm-agent-row-bearer .flm-agent-name,
.flm-agent-row-bearer .flm-agent-did {
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flm-agent-meta { flex: 1; min-width: 0; }
.flm-agent-name { margin: 0; font-size: 13.5px; font-weight: 500; }
.flm-agent-did { margin: 2px 0 0; opacity: 0.55; font-size: 11px; }

/* §15.1: extra top padding on flare-bearer rows so the encirclement
   halo + Sauron eye don't clip against the row top border. */
.flm-agent-row-bearer { padding-top: 18px; padding-bottom: 14px; }
.flm-agent-avatar { flex-shrink: 0; }
.flm-agent-avatar-empty {
  width: 26px; height: 26px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.04);
  border: 1px dashed rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.5);
  flex-shrink: 0;
}

.flm-move-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  letter-spacing: 0.04em;
  padding: 7px 12px;
}
.flm-bearer-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(16, 185, 129, 0.15);
  color: rgb(16, 185, 129);
  font-size: 11px;
  letter-spacing: 0.05em;
  padding: 5px 10px;
  border-radius: 99px;
  text-transform: uppercase;
  font-weight: 600;
}

/* §23 (2026-05-14) — DUAL-SLOT BEARER LAYOUT ────────────────── */

.flm-card--bearer {
  /* Slightly tighter padding so the two columns breathe vs. the single
     centered list of the legacy section. */
  padding-bottom: 18px;
}

/* Two-column grid on desktop; collapses to stacked on tablet+. The two
   columns are visually distinct (corner = cyan, encirclement = violet).
   The whole grid sits below the section header. */
.flm-bearer-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
  margin-top: 12px;
}
@media (max-width: 1200px) {
  .flm-bearer-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
  .flm-bearer-grid { grid-template-columns: 1fr; gap: 14px; }
}

/* §pass9 (2026-05-15) — Triple-rail alignment.
   The overlay rail (SLOT 3) renders the same "WEARING · X" pill shape as
   slots 1+2 (`.flm-bearer-slot-pill--enc`), with a chevron affordance.
   Click opens an anchored popover with the 6 overlay choices (None + 5).
   Layout-identical to native pills so the three rails read as one family. */
.flm-overlay-picker {
  position: relative;
  display: inline-flex;
}
.flm-overlay-pill {
  /* Match .flm-bearer-slot-pill default; add chevron padding on the right. */
  padding-right: 22px;
  cursor: pointer;
  border-style: solid;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  text-transform: uppercase;
  white-space: nowrap;
}
.flm-overlay-pill[disabled] { opacity: 0.4; cursor: not-allowed; }
.flm-overlay-chevron {
  position: absolute;
  right: 8px; top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
  opacity: 0.85;
  transition: transform 0.18s ease;
}
.flm-overlay-picker--open .flm-overlay-chevron {
  transform: translateY(-50%) rotate(180deg);
}

/* Popover anchored beneath the pill */
.flm-overlay-popover {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 200px;
  z-index: 50;
  background: linear-gradient(180deg, rgba(18, 14, 30, 0.98), rgba(8, 6, 18, 0.98));
  border: 1px solid rgba(196, 181, 253, 0.42);
  border-radius: 10px;
  padding: 6px;
  box-shadow:
    0 12px 36px rgba(0, 0, 0, 0.6),
    0 0 18px -4px rgba(196, 181, 253, 0.35);
  display: flex; flex-direction: column; gap: 2px;
}
.flm-overlay-popover-item {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.7rem; font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(220, 215, 235, 0.85);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
  transition: background 0.14s ease, color 0.14s ease, border-color 0.14s ease;
}
.flm-overlay-popover-item:hover {
  background: rgba(196, 181, 253, 0.12);
  color: rgba(245, 240, 255, 1);
  border-color: rgba(196, 181, 253, 0.35);
}
.flm-overlay-popover-item--active {
  background: rgba(196, 181, 253, 0.18);
  color: rgba(245, 240, 255, 1);
  border-color: rgba(196, 181, 253, 0.55);
}
.flm-overlay-popover-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: rgba(196, 181, 253, 0.3);
  flex-shrink: 0;
}
.flm-overlay-popover-dot--on { background: rgba(196, 181, 253, 0.9); box-shadow: 0 0 6px rgba(196, 181, 253, 0.5); }

/* ─── §pass11 (2026-05-15) — Bearer picker popover ─────────────────────── */
/* The "Change bearer" / "Pick a bearer" button sits below the bearer row;
   clicking it opens a searchable popover with every owned agent. Required
   at 160-agent scale — the previous per-agent v-for was rendering ~500 list
   items across the 3 columns combined. */
.flm-bearer-pick-wrap {
  position: relative;
  margin-top: 12px;
}
.flm-bearer-pick-btn {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 14px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-radius: 7px;
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.32);
  background: rgba(var(--nc-primary-rgb), 0.05);
  color: rgba(var(--nc-primary-rgb), 0.95);
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}
.flm-bearer-pick-btn:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  border-style: solid;
}
.flm-bearer-pick-btn[disabled] { opacity: 0.4; cursor: not-allowed; }

/* Encirclement variant: violet accent to match column tinting. */
.flm-bearer-pick-btn--enc {
  border-color: rgba(167, 139, 250, 0.32);
  background: rgba(167, 139, 250, 0.05);
  color: rgba(196, 181, 253, 0.95);
}
.flm-bearer-pick-btn--enc:hover:not(:disabled) {
  background: rgba(167, 139, 250, 0.10);
  border-color: rgba(167, 139, 250, 0.55);
}

.flm-bearer-picker-popover {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 60;
  max-height: 360px;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, rgba(18, 14, 30, 0.985), rgba(8, 6, 18, 0.985));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
  border-radius: 10px;
  box-shadow:
    0 14px 40px rgba(0, 0, 0, 0.65),
    0 0 20px -4px rgba(var(--nc-primary-rgb), 0.32);
  overflow: hidden;
}
.flm-bearer-col:nth-child(2) .flm-bearer-picker-popover {
  border-color: rgba(167, 139, 250, 0.42);
  box-shadow:
    0 14px 40px rgba(0, 0, 0, 0.65),
    0 0 20px -4px rgba(167, 139, 250, 0.32);
}
.flm-bearer-picker-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.18);
}
.flm-bearer-picker-search {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  color: rgba(245, 240, 255, 1);
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 5px;
  outline: none;
  transition: border-color 0.14s ease;
}
.flm-bearer-picker-search:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
}
.flm-bearer-col:nth-child(2) .flm-bearer-picker-search:focus {
  border-color: rgba(167, 139, 250, 0.55);
}
.flm-bearer-picker-close {
  flex-shrink: 0;
  width: 26px; height: 26px;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 5px;
  color: rgba(220, 215, 235, 0.85);
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease, border-color 0.14s ease;
}
.flm-bearer-picker-close:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.18);
  color: #fff;
}
.flm-bearer-picker-meta {
  padding: 6px 12px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.05em;
  color: rgba(180, 175, 200, 0.7);
  text-transform: uppercase;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.flm-bearer-picker-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  list-style: none;
  margin: 0; padding: 4px 4px;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.35) transparent;
}
.flm-bearer-picker-list::-webkit-scrollbar { width: 7px; }
.flm-bearer-picker-list::-webkit-scrollbar-track { background: transparent; }
.flm-bearer-picker-list::-webkit-scrollbar-thumb {
  background: rgba(var(--nc-primary-rgb), 0.32);
  border-radius: 7px;
}
.flm-bearer-picker-item {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  transition: background 0.14s ease;
}
.flm-bearer-picker-item + .flm-bearer-picker-item {
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.flm-bearer-picker-item:hover {
  background: rgba(var(--nc-primary-rgb), 0.06);
}
.flm-bearer-col:nth-child(2) .flm-bearer-picker-item:hover {
  background: rgba(167, 139, 250, 0.06);
}
.flm-bearer-picker-item--current {
  background: rgba(var(--nc-primary-rgb), 0.10);
}
.flm-bearer-col:nth-child(2) .flm-bearer-picker-item--current {
  background: rgba(167, 139, 250, 0.10);
}
.flm-bearer-picker-init {
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem; font-weight: 700;
  color: rgba(245, 240, 255, 0.92);
  background: rgba(var(--nc-primary-rgb), 0.15);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35);
  border-radius: 50%;
}
.flm-bearer-col:nth-child(2) .flm-bearer-picker-init {
  background: rgba(167, 139, 250, 0.15);
  border-color: rgba(167, 139, 250, 0.35);
}
.flm-bearer-picker-meta-inner {
  min-width: 0;
}
.flm-bearer-picker-meta-inner .flm-agent-name {
  font-size: 0.74rem;
  font-weight: 600;
  color: rgba(245, 240, 255, 0.95);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flm-bearer-picker-meta-inner .flm-agent-did {
  font-size: 0.62rem;
  color: rgba(180, 175, 200, 0.7);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flm-bearer-picker-equip {
  flex-shrink: 0;
  padding: 5px 10px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  border-radius: 5px;
  cursor: pointer;
}
.flm-bearer-picker-current-pill {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.64rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: rgba(196, 181, 253, 0.95);
  background: rgba(167, 139, 250, 0.12);
  border: 1px solid rgba(167, 139, 250, 0.45);
  border-radius: 99px;
}
.flm-bearer-picker-empty {
  padding: 18px 12px;
  text-align: center;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.7rem;
  color: rgba(180, 175, 200, 0.65);
}

/* Empty-state row inside the bearer list (shown when no agent bears the slot) */
.flm-agent-row-empty {
  opacity: 0.66;
}
.flm-agent-name-empty {
  font-style: italic;
  color: rgba(220, 215, 235, 0.7);
}
.flm-bearer-col-hint {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(180, 175, 200, 0.65);
  margin: 4px 0 0;
}

/* Per-column wrapper with subtle accent border + radial wash so the two
   slots read as independent surfaces. §pass11 — overflow visible so the
   bearer picker popover (anchored to the "Change bearer" button) is not
   clipped at the column's bottom edge. */
.flm-bearer-col {
  position: relative; overflow: visible;
  padding: 18px 18px 14px;
  border-radius: 10px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  background:
    radial-gradient(circle at 100% 0%, rgba(var(--nc-primary-rgb), 0.06), transparent 50%),
    rgba(var(--nc-primary-rgb), 0.018);
  transition: border-color 0.22s, background 0.22s;
}
.flm-bearer-col:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.18);
}
/* Encirclement column gets a violet tint to visually distinguish slot 2. */
.flm-bearer-col:nth-child(2) {
  background:
    radial-gradient(circle at 100% 0%, rgba(167, 139, 250, 0.08), transparent 50%),
    rgba(167, 139, 250, 0.015);
}
.flm-bearer-col:nth-child(2):hover {
  border-color: rgba(167, 139, 250, 0.25);
}

.flm-bearer-col-head { margin-bottom: 14px; }
.flm-bearer-col-eyebrow {
  display: block;
  font-family: ui-monospace, monospace;
  font-size: 9.5px; letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-bottom: 5px;
}
.flm-bearer-col:nth-child(2) .flm-bearer-col-eyebrow {
  color: rgba(167, 139, 250, 0.95);
}
.flm-bearer-col-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 600; color: #fff;
  margin: 0 0 6px;
}
.flm-bearer-col-icon {
  color: rgba(var(--nc-primary-rgb), 0.95);
  flex-shrink: 0;
}
.flm-bearer-col-icon :deep(svg) { width: 18px; height: 18px; }
.flm-bearer-col:nth-child(2) .flm-bearer-col-icon {
  color: rgba(167, 139, 250, 0.95);
}
.flm-bearer-col-sub {
  font-size: 12px; line-height: 1.55;
  color: rgba(220, 220, 235, 0.7);
  margin: 0;
}
.flm-bearer-col-sub strong { color: var(--text-bright, #fff); font-weight: 600; }

/* The list within the column reuses .flm-agent-list but with tighter gaps */
.flm-bearer-list {
  margin-top: 10px;
}
.flm-bearer-list--disabled {
  opacity: 0.55; filter: saturate(0.7);
}

/* Per-slot equip buttons — tinted by slot color (cyan / violet) */
.flm-equip-btn {
  font-size: 11px;
  padding: 6px 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 600;
  border-width: 1px;
  border-style: solid;
}
.flm-equip-btn--corner {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.35);
  color: rgba(var(--nc-primary-rgb), 1);
}
.flm-equip-btn--corner:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.16);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
}
.flm-equip-btn--enc {
  background: rgba(167, 139, 250, 0.08);
  border-color: rgba(167, 139, 250, 0.35);
  color: rgba(167, 139, 250, 1);
}
.flm-equip-btn--enc:hover:not(:disabled) {
  background: rgba(167, 139, 250, 0.16);
  border-color: rgba(167, 139, 250, 0.6);
}

/* Slot-bearer pill — looks like the §21 BEARER pill but per-slot tinted */
.flm-bearer-slot-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: ui-monospace, monospace;
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 600;
  padding: 5px 8px 5px 10px;
  border-radius: 99px;
  border: 1px solid;
  white-space: nowrap;
}
.flm-bearer-slot-pill--corner {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.18);
}
.flm-bearer-slot-pill--enc {
  color: rgba(167, 139, 250, 1);
  background: rgba(167, 139, 250, 0.12);
  border-color: rgba(167, 139, 250, 0.45);
  box-shadow: 0 0 14px rgba(167, 139, 250, 0.18);
}
.flm-bearer-slot-pill--disabled {
  color: rgba(220, 220, 235, 0.4);
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: none;
}
.flm-bearer-slot-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
  animation: flm-slot-pulse 2s ease-in-out infinite;
}
@keyframes flm-slot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.45; transform: scale(0.85); }
}

/* Inline "remove this slot" X button inside the BEARER pill */
.flm-bearer-slot-clear {
  display: inline-flex; align-items: center; justify-content: center;
  width: 18px; height: 18px;
  margin-left: 2px;
  border: 1px solid currentColor;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  cursor: pointer;
  opacity: 0.55;
  transition: opacity 0.18s, background 0.18s, transform 0.18s;
}
.flm-bearer-slot-clear:hover:not(:disabled) {
  opacity: 1;
  background: rgba(255, 255, 255, 0.06);
  transform: scale(1.06);
}
.flm-bearer-slot-clear:disabled {
  opacity: 0.3; cursor: not-allowed;
}
.flm-bearer-slot-clear :deep(svg) {
  width: 10px; height: 10px;
}

/* "Tip — equip both on same agent" hint banner */
.flm-bearer-tip {
  display: flex; align-items: flex-start; gap: 10px;
  margin: 18px 4px 4px;
  padding: 12px 14px;
  border-radius: 6px;
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.25);
  background: rgba(var(--nc-primary-rgb), 0.03);
  font-size: 12px;
  line-height: 1.55;
  color: rgba(220, 220, 235, 0.78);
}
.flm-bearer-tip em {
  color: rgba(var(--nc-primary-rgb), 1);
  font-style: italic;
  font-weight: 500;
}
.flm-bearer-tip :deep(svg) {
  color: rgba(var(--nc-primary-rgb), 0.85);
  flex-shrink: 0;
  margin-top: 2px;
}

/* Reduced-motion */
@media (prefers-reduced-motion: reduce) {
  .flm-bearer-slot-dot { animation: none !important; }
  .flm-bearer-slot-clear:hover { transform: none !important; }
}

.flm-spin { animation: flm-spin 1s linear infinite; }
@keyframes flm-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.flm-error {
  margin-top: 12px;
  font-size: 12px;
  color: rgb(239, 68, 68);
}
.flm-success {
  margin-top: 12px;
  font-size: 13px;
  color: rgb(16, 185, 129);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 640px) {
  .flm-h1 { font-size: 28px; }
  .flm-flare-display { flex-direction: column; align-items: flex-start; padding: 16px; gap: 14px; }
  .flm-agent-row { flex-wrap: wrap; }
  .flm-move-btn { width: 100%; justify-content: center; margin-top: 8px; }
}

/* ── MULTI-FLARE PICKER (PB-1 §12, 2026-05-11) ──────────────── */
.flm-slot-preview {
  position: relative;
  display: flex; flex-direction: column; align-items: center;
  gap: 10px; padding: 22px 16px;
  margin-bottom: 22px;
  border-radius: 8px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.flm-slot-preview-label {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.16em;
  color: var(--muted); text-transform: uppercase;
}
.flm-slot-preview-stack {
  position: relative; display: inline-block;
}
.flm-slot-preview-noenc {
  display: inline-flex; align-items: center; justify-content: center;
  width: 72px; height: 72px; border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb),0.18) 0%, rgba(var(--nc-primary-rgb),0.04) 80%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
}
.flm-slot-preview-initials {
  font-family: var(--mono); font-size: 24px; font-weight: 600;
  color: var(--nc-primary); letter-spacing: 0.04em;
}
.flm-slot-preview-corner {
  position: absolute;
  bottom: -6px; right: -6px;
  z-index: 3;
}
.flm-slot-preview-caption {
  font-size: 12px; color: var(--text-secondary); margin: 0;
}
.flm-slot-preview-sep { color: var(--muted); margin: 0 6px; }

.flm-slot-h3 {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em;
  color: var(--nc-primary); text-transform: uppercase;
  margin: 18px 0 10px; font-weight: 600;
}
.flm-slot-h3-enc { color: rgb(196, 181, 253); }

.flm-slot-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
  margin-bottom: 8px;
}
.flm-slot-card {
  position: relative;
  display: flex; flex-direction: column; align-items: center;
  justify-content: center;
  gap: 8px; padding: 16px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: rgba(var(--nc-primary-rgb), 0.02);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, transform 0.15s;
  font-family: inherit;
}
.flm-slot-card:hover:not(:disabled) {
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  background: rgba(var(--nc-primary-rgb), 0.06);
  transform: translateY(-1px);
}
.flm-slot-card:disabled { opacity: 0.5; cursor: not-allowed; }
.flm-slot-card--active {
  border-color: var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.1);
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.3);
}
.flm-slot-card-label {
  font-size: 12px; font-weight: 600; color: var(--text-bright);
  letter-spacing: 0.02em;
}
.flm-slot-card-active-tag {
  position: absolute;
  top: 6px; right: 8px;
  font-family: var(--mono); font-size: 8px; letter-spacing: 0.12em;
  color: #4ade80;
  padding: 2px 5px; border-radius: 3px;
  background: rgba(74, 222, 128, 0.1);
  border: 1px solid rgba(74, 222, 128, 0.28);
  text-transform: uppercase;
}
.flm-slot-card--clear { opacity: 0.65; }
.flm-slot-card--clear:hover { opacity: 1; }
.flm-slot-card-icon-muted { color: var(--muted); width: 22px; height: 22px; }
.flm-slot-card--enc {
  background: rgba(67, 20, 110, 0.07);
  border-color: rgba(88, 28, 135, 0.25);
}
.flm-slot-card--enc.flm-slot-card--active {
  border-color: rgb(196, 181, 253);
  background: rgba(67, 20, 110, 0.18);
  box-shadow: 0 0 0 1px rgba(88, 28, 135, 0.45);
}

/* §14 — Variant picker grid. xl-size previews so each variant looks
   meaningful at glance; the cards scale down responsively below 760px. */
.flm-slot-variant-hint {
  font-size: 12.5px;
  color: var(--text-secondary);
  margin: 0 0 14px 0;
  line-height: 1.55;
  max-width: 640px;
}
.flm-slot-variant-hint em {
  color: var(--text-bright);
  font-style: italic;
}
.flm-variant-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
  margin-bottom: 12px;
}

/* §28 polish 7 (2026-05-15) — Overlay-section grid (Glitch / Cascade /
   panic-a/b/c tournament tiles). Tighter minmax + smaller tile padding
   so the avatars don't feel like floating thumbs in oversized cards.
   Same active-state visuals as the variant grid; only sizing differs. */
.flm-variant-grid--overlay {
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.flm-variant-grid--overlay .flm-variant-card {
  padding: 24px 14px 14px;
  gap: 10px;
}
.flm-variant-grid--overlay .flm-variant-card .flm-variant-label {
  font-size: 0.78rem;
  text-align: center;
}
.flm-variant-grid--overlay .flm-variant-card .flm-variant-sub {
  font-size: 0.66rem;
  text-align: center;
  line-height: 1.3;
}
.flm-variant-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 14px;
  padding: 38px 18px 18px;  /* §15: extra top padding for Sauron eye halo */
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.55);
  background:
    radial-gradient(circle at 50% 110%, rgba(127, 29, 29, 0.07) 0%, transparent 60%),
    linear-gradient(180deg, rgba(15, 12, 22, 0.85) 0%, rgba(0, 0, 0, 0.95) 100%);
  cursor: pointer;
  transition: border-color 0.22s, transform 0.18s, box-shadow 0.22s;
  font-family: inherit;
  color: rgba(220, 220, 230, 0.92);
  /* §15: visible overflow so the Sauron eye flame halo doesn't get clipped
     at the card top. The card retains rounded corners via border-radius +
     background, and inner content is naturally constrained by padding. */
  overflow: visible;
  isolation: isolate;
}
.flm-variant-card:hover:not(:disabled) {
  border-color: rgba(196, 181, 253, 0.5);
  transform: translateY(-2px);
  box-shadow:
    0 8px 24px rgba(0, 0, 0, 0.5),
    0 0 0 1px rgba(196, 181, 253, 0.15);
}

/* §pass43c (2026-05-19) — Overlay picker tiles: xl preview + hover-scale.
   The preview wrapper transitions a transform on the FlareEncirclement
   so users get a satisfying enlarge-on-hover signal that they can
   inspect the burst-event animation cycle without clicking. */
.flm-variant-card--overlay {
  padding: 28px 18px 18px;
}
.flm-ov-preview-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.22s ease, filter 0.22s ease;
}
.flm-variant-card--overlay:hover:not(:disabled) .flm-ov-preview-wrap {
  transform: scale(1.08);
  filter: drop-shadow(0 4px 14px rgba(196, 181, 253, 0.35));
}
.flm-variant-card--overlay.flm-variant-card--active .flm-ov-preview-wrap {
  filter: drop-shadow(0 4px 18px rgba(196, 181, 253, 0.55));
}
@media (prefers-reduced-motion: reduce) {
  .flm-ov-preview-wrap { transition: none; }
  .flm-variant-card--overlay:hover .flm-ov-preview-wrap { transform: none; }
}
.flm-variant-card:disabled { opacity: 0.55; cursor: not-allowed; }
.flm-variant-card--active {
  border-color: rgba(196, 181, 253, 0.9);
  background:
    radial-gradient(circle at 50% 110%, rgba(127, 29, 29, 0.14) 0%, transparent 60%),
    linear-gradient(180deg, rgba(35, 16, 65, 0.55) 0%, rgba(8, 0, 18, 1) 100%);
  box-shadow:
    0 0 0 1px rgba(196, 181, 253, 0.45),
    0 0 22px -4px rgba(91, 33, 158, 0.55);
}
.flm-variant-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  text-align: center;
  margin-top: 4px;
}
.flm-variant-label {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgba(220, 200, 255, 0.95);
}
.flm-variant-card--active .flm-variant-label {
  color: rgb(196, 181, 253);
  text-shadow: 0 0 10px rgba(167, 139, 250, 0.4);
}
.flm-variant-sub {
  font-size: 11px;
  color: rgba(180, 180, 200, 0.65);
  line-height: 1.5;
  max-width: 240px;
}

/* §15.3 — locked variants get a 🔒 SOON pill in the corner. */
.flm-variant-card--locked {
  opacity: 0.82;
}
.flm-variant-card--locked:hover:not(:disabled) {
  opacity: 1;
}

/* §19/§20 — Section heads for EARNED vs SEASONAL vs COMING SOON variant groups. */
.flm-variant-section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  margin: 18px 0 12px;
  padding: 0;
  line-height: 1;
}
.flm-variant-section-head--earned {
  color: rgba(196, 181, 253, 0.95);
  text-shadow: 0 0 10px rgba(167, 139, 250, 0.32);
}
.flm-variant-section-head--locked {
  color: rgba(252, 211, 77, 0.88);
  text-shadow: 0 0 10px rgba(252, 211, 77, 0.18);
  margin-top: 28px;
  padding-top: 18px;
  border-top: 1px dashed rgba(252, 211, 77, 0.18);
}
.flm-variant-section-icon {
  font-size: 14px;
  width: 14px;
  height: 14px;
  display: inline-block;
  vertical-align: -2px;
}
.flm-variant-section-sub {
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.08em;
  color: rgba(180, 180, 200, 0.6);
  text-transform: none;
}

/* §21 — section count chip + IN-SEASON pulse chip on the section heads. */
.flm-variant-section-count {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.10em;
  padding: 2px 7px;
  border-radius: 999px;
  color: rgba(220, 220, 235, 0.95);
  background: rgba(40, 40, 60, 0.55);
  border: 1px solid rgba(167, 139, 250, 0.28);
}
.flm-variant-section-count--in-season {
  color: rgba(254, 243, 199, 0.98);
  background: rgba(234, 88, 12, 0.32);
  border-color: rgba(254, 215, 170, 0.85);
  text-shadow: 0 0 6px rgba(252, 211, 77, 0.55);
  animation: flm-section-count-pulse 2.6s ease-in-out infinite;
}
.flm-variant-section-count--in-season :deep(svg) {
  width: 11px;
  height: 11px;
}
@keyframes flm-section-count-pulse {
  0%, 100% { opacity: 0.92; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.06); }
}
.flm-variant-section-head--earned .flm-variant-section-count {
  color: rgba(216, 200, 255, 0.98);
  background: rgba(91, 33, 158, 0.32);
  border-color: rgba(196, 181, 253, 0.55);
}
.flm-variant-section-head--locked .flm-variant-section-count {
  color: rgba(254, 243, 199, 0.95);
  background: rgba(120, 53, 15, 0.35);
  border-color: rgba(252, 211, 77, 0.42);
}
.flm-variant-grid--locked {
  /* Subtle inset for the locked grid: faintly de-saturate the row so the
     EARNED grid above is the dominant visual. Cosmetic — selection still
     works inside this grid (achievement gating is roadmap'd). */
  filter: saturate(0.92);
}
.flm-variant-grid--locked .flm-variant-card:hover:not(:disabled) {
  filter: saturate(1.05);
}

/* §20 — SEASONAL section (autumn-warmth section head; subtle warm tint
   on the grid; in-season variants get a pulse-highlight ring). */
.flm-variant-section-head--seasonal {
  color: rgba(251, 146, 60, 0.95);
  text-shadow: 0 0 10px rgba(234, 88, 12, 0.32);
  margin-top: 28px;
  padding-top: 18px;
  border-top: 1px dashed rgba(251, 146, 60, 0.22);
}
.flm-variant-grid--seasonal {
  /* Slight warm-glow border so this row reads as "different category"
     without competing with EARNED's lavender. */
}
.flm-variant-seasonal-tag,
.flm-variant-in-season-tag {
  position: absolute;
  top: 8px; right: 8px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  padding: 3px 7px;
  border-radius: 3px;
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.flm-variant-seasonal-tag {
  color: rgba(251, 146, 60, 0.95);
  background: rgba(251, 146, 60, 0.1);
  border: 1px solid rgba(251, 146, 60, 0.4);
}
.flm-variant-in-season-tag {
  color: rgba(254, 243, 199, 0.98);
  background: rgba(234, 88, 12, 0.22);
  border: 1px solid rgba(254, 215, 170, 0.88);
  text-shadow: 0 0 6px rgba(252, 211, 77, 0.55);
  /* §20: gentle pulse so the active-season tile draws the eye */
  animation: fc-in-season-pulse 2.6s ease-in-out infinite;
}
.flm-variant-seasonal-tag :deep(svg),
.flm-variant-in-season-tag :deep(svg) {
  width: 10px; height: 10px;
}
.flm-variant-card--in-season {
  /* Subtle warm ring so the in-season tile pops without overcomplicating
     the EARNED section's dominant hierarchy. */
  box-shadow:
    0 0 0 1px rgba(252, 211, 77, 0.45),
    0 0 16px -2px rgba(234, 88, 12, 0.35);
}
.flm-variant-card--in-season:hover:not(:disabled) {
  box-shadow:
    0 0 0 1px rgba(254, 215, 170, 0.7),
    0 0 24px -2px rgba(252, 211, 77, 0.55);
}

@keyframes fc-in-season-pulse {
  0%, 100% { opacity: 0.9; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.04); }
}

/* §20 — ADMIN CORNER BADGE PICKER (gold-tinted hierarchy, admin-only). */
.flm-slot-h3-admin {
  color: rgba(252, 211, 77, 0.95);
  text-shadow: 0 0 12px rgba(252, 211, 77, 0.32);
  /* Visual hint that this is a special-perks section */
}
.flm-variant-card--admin {
  /* Gold accent border + warmer hover state */
  border-color: rgba(252, 211, 77, 0.22) !important;
}
.flm-variant-card--admin:hover:not(:disabled) {
  border-color: rgba(252, 211, 77, 0.65) !important;
  box-shadow:
    0 8px 24px rgba(0, 0, 0, 0.55),
    0 0 0 1px rgba(252, 211, 77, 0.42),
    0 0 28px -8px rgba(252, 211, 77, 0.55);
}
.flm-variant-card--admin.flm-variant-card--active {
  border-color: rgba(254, 240, 138, 1) !important;
  background:
    radial-gradient(circle at 50% 110%, rgba(252, 211, 77, 0.18) 0%, transparent 60%),
    linear-gradient(180deg, rgba(60, 40, 8, 0.55) 0%, rgba(20, 12, 0, 1) 100%);
  box-shadow:
    0 0 0 1px rgba(254, 240, 138, 0.85),
    0 0 32px -4px rgba(252, 211, 77, 0.7);
}
.flm-variant-admin-tag {
  position: absolute;
  top: 8px; right: 8px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  padding: 3px 7px;
  border-radius: 3px;
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: rgba(254, 243, 199, 0.98);
  background: rgba(120, 53, 15, 0.4);
  border: 1px solid rgba(252, 211, 77, 0.55);
}
.flm-variant-admin-tag :deep(svg) {
  width: 10px; height: 10px;
}
.flm-variant-locked-tag {
  position: absolute;
  top: 8px; right: 8px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.14em;
  color: rgba(252, 211, 77, 0.95);
  padding: 3px 7px;
  border-radius: 3px;
  background: rgba(252, 211, 77, 0.08);
  border: 1px solid rgba(252, 211, 77, 0.35);
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.flm-variant-locked-tag :deep(svg) {
  width: 10px;
  height: 10px;
}

/* ════════════════════════════════════════════════════════════════
   §2026-06-29 — AAA+ polish pass. CSS-only + scoped; NO template or
   FlareEncirclement changes (catalog component is off-limits). Goal:
   let the FLARE be the hero of each preview tile (recede the avatar
   initials), unify the radius/depth scale, tighten section rhythm.
   ════════════════════════════════════════════════════════════════ */

/* 1 — Recede the preview-tile initials. In a flare PICKER the centre
   letters are noise; the ring is what's being chosen. Ghost them so the
   variant reads instantly. Scoped to picker tiles via :deep — the
   "this is you" composition (.flm-slot-preview) keeps its bright avatar. */
.flm-variant-card :deep(.fc-encircle-initials),
.flm-slot-card :deep(.fc-encircle-initials) {
  font-size: 14px !important;   /* shrink from 36px → a tiny, quiet monogram */
  font-weight: 400;
  opacity: 0.22;
  color: rgba(214, 214, 234, 0.9);
  letter-spacing: 0.12em;
  transition: opacity 0.2s ease;
}
.flm-variant-card:hover :deep(.fc-encircle-initials),
.flm-variant-card--active :deep(.fc-encircle-initials) { opacity: 0.42; }

/* 2 — Variant cards: rounder, deeper, cleaner edge; even hover lift. */
.flm-variant-card {
  border-radius: 16px;
  border-color: rgba(255, 255, 255, 0.06);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 10px 30px -24px rgba(0, 0, 0, 0.9);
}
.flm-variant-card:hover:not(:disabled) {
  box-shadow:
    0 16px 40px -20px rgba(0, 0, 0, 0.85),
    0 0 0 1px rgba(196, 181, 253, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.flm-variant-card--active {
  box-shadow:
    0 0 0 1px rgba(196, 181, 253, 0.5),
    0 0 26px -4px rgba(91, 33, 158, 0.6),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.flm-variant-grid { gap: 16px; }
.flm-variant-label { letter-spacing: 0.14em; }

/* 3 — Slot cards + grid: unify to the rounded scale, richer active glow.
   The "Hide …" tiles read as the quiet opt-out (dashed, low-key). */
.flm-slot-card { border-radius: 12px; }
.flm-slot-card:hover:not(:disabled) {
  box-shadow: 0 8px 22px -16px rgba(var(--nc-primary-rgb), 0.7);
}
.flm-slot-card--active {
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.4), 0 10px 26px -16px rgba(var(--nc-primary-rgb), 0.55);
}
.flm-slot-card--clear {
  border-style: dashed;
  border-color: rgba(255, 255, 255, 0.12);
}

/* 4 — The "this is you" composition box: a proper stage, not a flat panel. */
.flm-slot-preview {
  border-radius: 16px;
  padding: 26px 16px 22px;
  background:
    radial-gradient(120% 90% at 50% -10%, rgba(var(--nc-primary-rgb), 0.10), transparent 62%),
    rgba(0, 0, 0, 0.3);
  border-color: rgba(var(--nc-primary-rgb), 0.22);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 18px 44px -30px rgba(0, 0, 0, 0.9);
}

/* 5 — Cards: consistent radius + a touch more depth for page rhythm. */
.flm-card {
  border-radius: 18px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035), 0 20px 50px -36px rgba(0, 0, 0, 0.9);
}

/* 6 — Section heads: a hairline baseline so EARNED / SEASONAL / COMING
   SOON groups have clean vertical rhythm instead of floating. */
.flm-variant-section-head {
  align-items: center;
  padding-bottom: 11px;
  margin-bottom: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

/* Mobile: tighter grid + smaller padding so it stays one card per row */
@media (max-width: 640px) {
  .flm-variant-grid { grid-template-columns: 1fr; gap: 12px; }
  .flm-variant-card { padding: 18px 14px 16px; gap: 12px; }
}
</style>
