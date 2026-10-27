<!--
  AgentForge — single source of truth for "create a new sovereign agent".

  Shipped 2026-05-15 §pass15 (Phase F). Replaces the two divergent wizards
  that existed in parallel:
    • OnboardingWizard.vue — marketing-friendly, template-first, 5 steps
    • AgentBuilder.vue     — granular form, capability-rich, 4 steps

  Both views are now route aliases that render AgentForge. AgentForge takes
  the best of each:
    1. Welcome / Why-bother      (from Onboarding step 0)
    2. Template + Identity       (Onboarding template grid + AB identity form)
    3. Capabilities + Auth        (AB step 2 + step 3 merged)
    4. Deploy                    (Onboarding deploy + AB credentials modal blend)
    5. You're Live / What's next (Onboarding step 4)

  Companion infrastructure:
    • components/common/InfoTooltip.vue — passive / first-touch / forced-read
    • composables/useTutorialRegistry.ts — central topic catalogue
    • localStorage:agentForge:progress:v1 — resume after refresh
    • /agent-builder and /agent-forge render this view. /onboarding did too until 2026-10-09; it is the
      Quick onboarding page now (views/QuickOnboarding.vue: a name in, an agent identity out).

  Pattern doctrine (see feedback_*.md memories):
    • Theme-aware via --nc-primary CSS vars; no scoped emerald shims
    • Mobile-aware via composables/useViewport (no hardcoded breakpoints)
    • reduced-motion respected on every keyframe
    • ViewAmbient is the global atmosphere — view body stays transparent
-->
<template>
  <div class="afg-root" :class="{ 'afg-mobile': isMobile }">
    <!-- Hero header -->
    <header class="afg-hero">
      <div class="afg-hero-inner">
        <div class="afg-hero-left">
          <span class="afg-hero-eyebrow">{{ t('agentForgeView.eyebrow') }}</span>
          <h1 class="afg-hero-title" data-tour="forge-hero">
            <span class="afg-hero-title-prefix">{{ t('agentForgeView.titlePrefix') }}</span>
            <span class="afg-hero-title-accent">{{ t('agentForgeView.titleAccent') }}</span>
          </h1>
          <p class="afg-hero-subtitle">{{ tp('agentForgeView.subtitle', 'Create the cryptographic identity, the {unit} wallet, and the runnable Docker bundle in one guided flow.', { unit: localCurrency }) }}</p>
        </div>

        <!-- Decorative SVG — a hex spinning slowly -->
        <div class="afg-hero-decor" aria-hidden="true">
          <svg viewBox="0 0 90 90" class="afg-hero-decor-svg">
            <defs>
              <linearGradient id="afg-decor-grad" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%"  stop-color="rgba(var(--nc-primary-rgb), 0.85)" />
                <stop offset="100%" stop-color="rgba(var(--nc-primary-rgb), 0.30)" />
              </linearGradient>
            </defs>
            <polygon points="45,5 80,25 80,65 45,85 10,65 10,25"
                     fill="none" stroke="url(#afg-decor-grad)" stroke-width="1.4" class="afg-decor-hex-outer"/>
            <polygon points="45,18 67,30 67,58 45,70 23,58 23,30"
                     fill="none" stroke="rgba(var(--nc-primary-rgb), 0.45)" stroke-width="1" class="afg-decor-hex-inner"/>
            <circle cx="45" cy="44" r="3" fill="rgba(var(--nc-primary-rgb), 0.9)" class="afg-decor-dot"/>
          </svg>
        </div>

        <button
          v-if="!isFinalStep"
          type="button"
          class="afg-hero-close"
          :class="{ 'afg-hero-close--locked': isDeploying }"
          :title="isDeploying ? t('agentForgeView.cancelLocked') : t('agentForgeView.cancel')"
          :aria-label="isDeploying ? t('agentForgeView.cancelLocked') : t('agentForgeView.cancel')"
          :disabled="isDeploying"
          @click="onAbortRequest"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
        </button>
      </div>
    </header>

    <!-- Stepper -->
    <div class="afg-stepper-wrap">
      <ol class="afg-stepper" data-tour="forge-stepper" :aria-label="t('agentForgeView.stepper.aria')">
        <!-- §pass17 — Completed steps are clickable (jump backward). Forward
             jumps are disallowed (would skip validation). Cursor + aria-* on
             clickable rows; disabled visual for in-progress/future. -->
        <li
          v-for="(s, i) in steps"
          :key="s.key"
          class="afg-step"
          :class="{
            'afg-step--active': i === currentStepIdx,
            'afg-step--done':   i <  currentStepIdx,
            'afg-step--clickable': i < currentStepIdx && !isDeploying && !(deploySuccess && currentStep.key === 'deploy'),
          }"
          :role="i < currentStepIdx ? 'button' : undefined"
          :tabindex="i < currentStepIdx ? 0 : undefined"
          :aria-label="i < currentStepIdx ? t('agentForgeView.stepper.jumpBackAria', { step: t('agentForgeView.steps.' + s.key + '.title') }) : undefined"
          @click="i < currentStepIdx && jumpToStep(i)"
          @keydown.enter.prevent="i < currentStepIdx && jumpToStep(i)"
          @keydown.space.prevent="i < currentStepIdx && jumpToStep(i)"
        >
          <span class="afg-step-num">
            <svg v-if="i < currentStepIdx" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
              <path d="M2 6 L5 9 L10 3" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span v-else>{{ i + 1 }}</span>
          </span>
          <span class="afg-step-label">{{ t('agentForgeView.steps.' + s.key + '.title') }}</span>
          <span v-if="i < steps.length - 1" class="afg-step-connector" aria-hidden="true"></span>
        </li>
      </ol>
      <div class="afg-stepper-mobile-pill" v-if="isPhone">
        <span class="afg-stepper-mobile-pill-num">{{ currentStepIdx + 1 }}</span>
        <span class="afg-stepper-mobile-pill-total">/ {{ steps.length }}</span>
        <span class="afg-stepper-mobile-pill-label">{{ t('agentForgeView.steps.' + currentStep.key + '.title') }}</span>
      </div>
    </div>

    <!-- Step content -->
    <main class="afg-stage">
      <Transition :name="transitionDirection === 'forward' ? 'afg-slide-fwd' : 'afg-slide-back'" mode="out-in">
        <!-- ───────────────────────────── STEP 1: WELCOME ───────────────────────────── -->
        <section v-if="currentStep.key === 'welcome'" key="welcome" class="afg-panel afg-panel--welcome">
          <h2 class="afg-panel-title">{{ t('agentForgeView.steps.welcome.heading') }}</h2>
          <p class="afg-panel-lead">{{ tp('agentForgeView.steps.welcome.lead', 'Five quick steps and your sovereign AI agent is live on the network — with its own identity, its own {unit} balance, and a runnable Docker bundle.', { unit: localCurrency }) }}</p>

          <div class="afg-value-grid">
            <div v-for="(v, idx) in valueProps" :key="v.key" class="afg-value-card" :style="{ '--idx': idx }">
              <span class="afg-value-icon" v-html="v.icon"></span>
              <h3 class="afg-value-title" :data-genesis="v.key === 'avt' ? genesisTile.title : undefined">{{ v.key === 'avt' ? genesisTile.title : t('agentForgeView.steps.welcome.values.' + v.key + '.title') }}</h3>
              <p class="afg-value-copy">{{ v.key === 'avt' ? genesisTile.copy : t('agentForgeView.steps.welcome.values.' + v.key + '.copy') }}</p>
            </div>
          </div>

          <div class="afg-roadmap">
            <h3 class="afg-roadmap-title">{{ t('agentForgeView.steps.welcome.roadmapTitle') }}</h3>
            <div class="afg-roadmap-grid">
              <div v-for="(rs, idx) in roadmapPreview" :key="rs.key" class="afg-roadmap-step" :style="{ '--idx': idx }">
                <span class="afg-roadmap-num">{{ String(idx + 1).padStart(2, '0') }}</span>
                <span class="afg-roadmap-step-title">{{ t('agentForgeView.steps.welcome.roadmap.' + rs.key + '.title') }}</span>
                <span class="afg-roadmap-step-copy">{{ t('agentForgeView.steps.welcome.roadmap.' + rs.key + '.copy') }}</span>
              </div>
            </div>
          </div>

          <p class="afg-language-note">{{ t('agentForgeView.steps.welcome.anyLang') }}</p>
        </section>

        <!-- ──────────────────── STEP 2: TEMPLATE + IDENTITY ──────────────────── -->
        <section v-else-if="currentStep.key === 'templateIdentity'" key="templateIdentity" class="afg-panel">
          <h2 class="afg-panel-title">{{ t('agentForgeView.steps.templateIdentity.heading') }}</h2>
          <p class="afg-panel-lead">{{ t('agentForgeView.steps.templateIdentity.lead') }}</p>

          <!-- Template grid -->
          <div class="afg-template-grid">
            <button
              v-for="(tpl, idx) in shownTemplates"
              :key="tpl.id"
              type="button"
              class="afg-template-card"
              :class="{ 'afg-template-card--selected': formData.templateId === tpl.id }"
              :style="{ '--idx': idx }"
              @click="selectTemplate(tpl.id)"
            >
              <span v-if="tpl.featured" class="afg-template-badge">{{ t('agentForgeView.steps.templateIdentity.featured') }}</span>
              <span class="afg-template-icon">{{ tpl.icon }}</span>
              <h3 class="afg-template-name">{{ t('agentForgeView.steps.templateIdentity.templates.' + tpl.id + '.name') }}</h3>
              <p class="afg-template-tagline">{{ t('agentForgeView.steps.templateIdentity.templates.' + tpl.id + '.tagline') }}</p>
              <p class="afg-template-description">{{ t('agentForgeView.steps.templateIdentity.templates.' + tpl.id + '.description') }}</p>
              <div class="afg-template-tags">
                <span v-for="tag in tpl.tags" :key="tag" class="afg-template-tag">{{ tag }}</span>
              </div>
              <span v-if="formData.templateId === tpl.id" class="afg-template-checkmark" aria-hidden="true">
                <svg viewBox="0 0 14 14" width="14" height="14"><path d="M3 7 L6 10 L11 4" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </span>
            </button>
          </div>

          <!-- Divider with sample-data autofill (§pass16) -->
          <div class="afg-divider afg-divider--with-action">
            <span>{{ t('agentForgeView.steps.templateIdentity.identityHeading') }}</span>
            <button
              v-if="formData.templateId"
              type="button"
              class="afg-divider-action"
              @click="fillSampleData"
              :title="t('agentForgeView.steps.templateIdentity.sampleDataTitle')"
            >
              <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
                <path d="M2 6 L10 6 M6 2 L10 6 L6 10" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              {{ t('agentForgeView.steps.templateIdentity.sampleData') }}
            </button>
          </div>

          <!-- §pass17 — Template-required gate. When no template is picked,
               dim the identity form + show a clear "pick a template above"
               hint so the user knows the order. -->
          <div v-if="!formData.templateId" class="afg-gate-hint">
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M8 12 L8 4 M4 8 L8 4 L12 8" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span>{{ t('agentForgeView.steps.templateIdentity.pickTplFirst') }}</span>
          </div>

          <!-- Identity fields -->
          <div class="afg-form" :class="{ 'afg-form--gated': !formData.templateId }">
            <div class="afg-field afg-field--name-pair">
              <label class="afg-label">
                {{ t('agentForgeView.fields.name.label') }} <span class="afg-required">*</span>
                <InfoTooltip topic="did" placement="right" size="xs" />
              </label>
              <div class="afg-input-wrap">
                <input
                  v-model="formData.name"
                  @input="onNameInput"
                  type="text"
                  class="afg-input"
                  :class="{ 'afg-input--error': nameError, 'afg-input--valid': nameValid }"
                  :placeholder="t('agentForgeView.fields.name.placeholder')"
                  maxlength="100"
                  autocomplete="off"
                />
                <span class="afg-input-status">
                  <svg v-if="nameValid" viewBox="0 0 12 12" width="14" height="14" aria-hidden="true">
                    <path d="M2 6 L5 9 L10 3" stroke="rgba(34,197,94,0.95)" stroke-width="1.8" fill="none" stroke-linecap="round"/>
                  </svg>
                </span>
              </div>
              <p v-if="nameError" class="afg-error">{{ nameError }}</p>
              <p v-else class="afg-hint">
                {{ t('agentForgeView.fields.name.hint') }}
                <span v-if="!hriManuallyEdited && formData.name" class="afg-name-autofill-note">
                  <svg viewBox="0 0 12 12" width="9" height="9" aria-hidden="true">
                    <path d="M6 2 L6 9 M3 6 L6 9 L9 6" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                  {{ t('agentForgeView.fields.name.autoFillsHri') }}
                </span>
              </p>
            </div>

            <div class="afg-field">
              <label class="afg-label">
                {{ t('agentForgeView.fields.hri.label') }} <span class="afg-required">*</span>
                <InfoTooltip topic="hri-slug" placement="right" size="xs" />
              </label>
              <div class="afg-input-wrap">
                <input
                  v-model="formData.hri"
                  @input="hriManuallyEdited = true"
                  type="text"
                  class="afg-input"
                  :class="{ 'afg-input--error': hriError, 'afg-input--valid': hriValid }"
                  :placeholder="t('agentForgeView.fields.hri.placeholder')"
                  maxlength="60"
                  autocomplete="off"
                />
                <span class="afg-input-status">
                  <svg v-if="hriValid" viewBox="0 0 12 12" width="14" height="14" aria-hidden="true">
                    <path d="M2 6 L5 9 L10 3" stroke="rgba(34,197,94,0.95)" stroke-width="1.8" fill="none" stroke-linecap="round"/>
                  </svg>
                  <svg v-else-if="formData.hri.length > 0" viewBox="0 0 12 12" width="14" height="14" aria-hidden="true">
                    <path d="M3 3 L9 9 M9 3 L3 9" stroke="rgba(239,68,68,0.95)" stroke-width="1.8" stroke-linecap="round"/>
                  </svg>
                </span>
              </div>
              <p v-if="hriError" class="afg-error">{{ hriError }}</p>
              <p v-else class="afg-hint">
                {{ t('agentForgeView.fields.hri.hintPrefix') }}
                <code class="afg-code">{{ formData.hri || 'your-agent' }}.agent</code>
              </p>
            </div>

            <div class="afg-field">
              <label class="afg-label">
                {{ t('agentForgeView.fields.description.label') }} <span class="afg-required">*</span>
              </label>
              <textarea
                v-model="formData.description"
                class="afg-input afg-textarea"
                :class="{ 'afg-input--error': descriptionError, 'afg-input--valid': descValid }"
                :placeholder="currentTemplate?.descriptionPlaceholder || t('agentForgeView.fields.description.placeholder')"
                rows="3"
                maxlength="500"
              ></textarea>
              <div class="afg-textarea-meta">
                <p v-if="descriptionError" class="afg-error">{{ descriptionError }}</p>
                <span v-else class="afg-hint">{{ t('agentForgeView.fields.description.hint') }}</span>
                <span class="afg-char-count" :class="{ 'afg-char-count--warn': formData.description.length > 420 }">
                  {{ formData.description.length }} / 500
                </span>
              </div>
            </div>

            <div class="afg-field afg-field--inline">
              <div class="afg-field-inline-item">
                <label class="afg-label">{{ t('agentForgeView.fields.version.label') }}</label>
                <input
                  v-model="formData.agentVersion"
                  type="text"
                  class="afg-input"
                  placeholder="1.0.0"
                  maxlength="20"
                  autocomplete="off"
                />
                <p class="afg-hint">{{ t('agentForgeView.fields.version.hint') }}</p>
              </div>
            </div>
          </div>
        </section>

        <!-- ───────────────── STEP 3: CAPABILITIES + AUTH ───────────────── -->
        <section v-else-if="currentStep.key === 'capabilitiesAuth'" key="capabilitiesAuth" class="afg-panel">
          <h2 class="afg-panel-title">{{ t('agentForgeView.steps.capabilitiesAuth.heading') }}</h2>
          <p class="afg-panel-lead">{{ t('agentForgeView.steps.capabilitiesAuth.lead') }}</p>

          <!-- A2A capabilities -->
          <div class="afg-subsection">
            <h3 class="afg-subsection-title">
              {{ t('agentForgeView.steps.capabilitiesAuth.a2aCaps') }}
              <InfoTooltip topic="a2a-auth" placement="right" size="xs" />
            </h3>
            <div class="afg-chip-grid">
              <button
                v-for="cap in capabilities"
                :key="cap.key"
                type="button"
                class="afg-chip"
                :class="{ 'afg-chip--selected': (formData as any)[cap.field] }"
                @click="(formData as any)[cap.field] = !(formData as any)[cap.field]"
              >
                <span class="afg-chip-box">
                  <svg v-if="(formData as any)[cap.field]" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                    <path d="M2 6 L5 9 L10 3" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/>
                  </svg>
                </span>
                <span class="afg-chip-text">
                  <span class="afg-chip-name">{{ t('agentForgeView.capabilities.' + cap.key + '.label') }}</span>
                  <span class="afg-chip-sub">{{ t('agentForgeView.capabilities.' + cap.key + '.sub') }}</span>
                </span>
              </button>
            </div>
            <p class="afg-hint afg-hint--block">{{ t('agentForgeView.steps.capabilitiesAuth.a2aHint') }}</p>
          </div>

          <div class="afg-section-divider"></div>

          <!-- Auth scheme -->
          <div class="afg-subsection">
            <h3 class="afg-subsection-title">
              {{ t('agentForgeView.steps.capabilitiesAuth.authScheme') }}
              <InfoTooltip topic="a2a-auth" placement="right" size="xs" />
            </h3>
            <div class="afg-radio-grid">
              <button
                v-for="auth in authSchemes"
                :key="auth.id"
                type="button"
                class="afg-radio-card"
                :class="{ 'afg-radio-card--selected': formData.authScheme === auth.id }"
                @click="formData.authScheme = auth.id"
              >
                <span class="afg-radio-dot"><span v-if="formData.authScheme === auth.id" class="afg-radio-dot-inner"></span></span>
                <div class="afg-radio-body">
                  <span class="afg-radio-name">{{ t('agentForgeView.authSchemes.' + auth.id + '.label') }}</span>
                  <span class="afg-radio-desc">{{ t('agentForgeView.authSchemes.' + auth.id + '.desc') }}</span>
                </div>
              </button>
            </div>

            <Transition name="afg-fade">
              <div v-if="formData.authScheme === 'oauth2'" class="afg-field afg-field--nested">
                <label class="afg-label">{{ t('agentForgeView.fields.tokenUrl.label') }}</label>
                <input
                  v-model="formData.tokenUrl"
                  type="url"
                  class="afg-input"
                  :class="{ 'afg-input--error': tokenUrlError }"
                  :placeholder="tokenUrlPlaceholder"
                />
                <p v-if="tokenUrlError" class="afg-error">{{ tokenUrlError }}</p>
                <p v-else class="afg-hint">{{ t('agentForgeView.fields.tokenUrl.hint') }}</p>
              </div>
            </Transition>
          </div>

          <div class="afg-section-divider"></div>

          <!-- Service / Provider -->
          <div class="afg-subsection">
            <h3 class="afg-subsection-title">{{ t('agentForgeView.steps.capabilitiesAuth.endpoint') }}</h3>
            <div class="afg-field">
              <label class="afg-label">{{ t('agentForgeView.fields.serviceUrl.label') }}</label>
              <input
                v-model="formData.serviceUrl"
                type="url"
                class="afg-input"
                :class="{ 'afg-input--error': serviceUrlError }"
                :placeholder="defaultServiceUrl"
              />
              <p v-if="serviceUrlError" class="afg-error">{{ serviceUrlError }}</p>
              <div v-else class="afg-hint-rich">
                <p class="afg-hint">{{ t('agentForgeView.fields.serviceUrl.hintHosted') }}</p>
                <p class="afg-hint afg-hint-or">{{ t('agentForgeView.fields.serviceUrl.hintOr') }}</p>
                <p class="afg-hint">{{ t('agentForgeView.fields.serviceUrl.hintSelfHost') }}</p>
              </div>
            </div>

            <div class="afg-field afg-field--inline">
              <div class="afg-field-inline-item">
                <label class="afg-label">{{ t('agentForgeView.fields.providerName.label') }}</label>
                <input
                  v-model="formData.providerName"
                  type="text"
                  class="afg-input"
                  :placeholder="formData.name || t('agentForgeView.fields.providerName.placeholder')"
                  maxlength="100"
                />
                <p class="afg-hint">{{ t('agentForgeView.fields.providerName.hint') }}</p>
              </div>
              <div class="afg-field-inline-item">
                <label class="afg-label">{{ t('agentForgeView.fields.providerUrl.label') }}</label>
                <input
                  v-model="formData.providerUrl"
                  type="url"
                  class="afg-input"
                  :class="{ 'afg-input--error': providerUrlError }"
                  placeholder="https://your-site.com"
                  maxlength="200"
                />
                <p v-if="providerUrlError" class="afg-error">{{ providerUrlError }}</p>
                <p v-else class="afg-hint">{{ t('agentForgeView.fields.providerUrl.hint') }}</p>
              </div>
            </div>
          </div>

          <!-- Tags (§pass17 — collapsible by default since most users won't customize) -->
          <div class="afg-section-divider"></div>
          <div class="afg-subsection">
            <button
              type="button"
              class="afg-disclosure"
              :class="{ 'afg-disclosure--open': tagsExpanded }"
              :aria-expanded="tagsExpanded"
              @click="tagsExpanded = !tagsExpanded"
            >
              <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" class="afg-disclosure-chev">
                <path d="M4 2 L8 6 L4 10" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span class="afg-disclosure-label">{{ t('agentForgeView.steps.capabilitiesAuth.tags') }}</span>
              <span v-if="!tagsExpanded && (templateTags.length + formData.customTags.length) > 0" class="afg-disclosure-count">
                {{ templateTags.length + formData.customTags.length }}
              </span>
              <span class="afg-disclosure-optional">{{ t('agentForgeView.steps.capabilitiesAuth.optionalMax', { n: 12 }) }}</span>
            </button>
            <Transition name="afg-disclose">
              <div v-if="tagsExpanded" class="afg-disclosure-body">
                <div class="afg-tag-input-wrap" @click="focusTagInput">
                  <span
                    v-for="tag in templateTags"
                    :key="`tpl-${tag}`"
                    class="afg-tag afg-tag--template"
                    :title="t('agentForgeView.steps.capabilitiesAuth.tagFromTemplate')"
                  >{{ tag }}</span>
                  <span
                    v-for="(tag, idx) in formData.customTags"
                    :key="`c-${tag}`"
                    class="afg-tag afg-tag--custom"
                  >
                    {{ tag }}
                    <button type="button" class="afg-tag-remove" @click.stop="removeCustomTag(idx)" :aria-label="t('agentForgeView.tagRemoveAria', { tag })">×</button>
                  </span>
                  <input
                    ref="tagInputRef"
                    v-model="tagInputValue"
                    type="text"
                    class="afg-tag-input"
                    :placeholder="formData.customTags.length === 0 ? t('agentForgeView.fields.tags.placeholder') : ''"
                    @keydown="onTagKeydown"
                    @blur="addCustomTag"
                    maxlength="30"
                  />
                </div>
                <p class="afg-hint afg-hint--block">{{ t('agentForgeView.fields.tags.hint') }}</p>
              </div>
            </Transition>
          </div>
        </section>

        <!-- ─────────────────────── STEP 4: DEPLOY ─────────────────────── -->
        <section v-else-if="currentStep.key === 'deploy'" key="deploy" class="afg-panel">
          <!-- Phase A: Pre-deploy review + deploy button -->
          <template v-if="!deploySuccess">
            <h2 class="afg-panel-title">{{ t('agentForgeView.steps.deploy.headingPre') }}</h2>
            <p class="afg-panel-lead">{{ t('agentForgeView.steps.deploy.leadPre') }}</p>

            <!-- Bootstrap status pill -->
            <div class="afg-bst" :class="`afg-bst--${bstStatus}`">
              <span class="afg-bst-dot"></span>
              <span v-if="bstStatus === 'acquiring'">{{ t('agentForgeView.bst.acquiring') }}</span>
              <span v-else-if="bstStatus === 'ready'">{{ t('agentForgeView.bst.ready') }} <span class="afg-bst-time">· {{ bstCountdown }}</span></span>
              <span v-else-if="bstStatus === 'expired'">{{ t('agentForgeView.bst.expired') }}</span>
              <span v-else-if="bstStatus === 'error'">{{ t('agentForgeView.bst.error') }}</span>
              <span v-else>{{ t('agentForgeView.bst.idle') }}</span>
              <button
                v-if="bstStatus === 'expired' || bstStatus === 'error' || bstStatus === 'idle'"
                type="button"
                class="afg-bst-retry"
                @click="acquireBootstrap"
              >{{ t('agentForgeView.bst.retry') }}</button>
              <InfoTooltip topic="bootstrap-token" placement="bottom" size="xs" />
            </div>

            <!-- Review block -->
            <div class="afg-review-grid">
              <div class="afg-review-card">
                <h3 class="afg-review-title">{{ t('agentForgeView.steps.deploy.review.template') }}</h3>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.kind') }}</span><strong>{{ currentTemplate?.icon }} {{ currentTemplate ? t('agentForgeView.steps.templateIdentity.templates.' + currentTemplate.id + '.name') : '—' }}</strong></div>
              </div>
              <div class="afg-review-card">
                <h3 class="afg-review-title">{{ t('agentForgeView.steps.deploy.review.identity') }}</h3>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.name') }}</span><strong>{{ formData.name }}</strong></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.hri') }}</span><code class="afg-code">{{ formData.hri }}.agent</code></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.version') }}</span><strong>{{ formData.agentVersion || '1.0.0' }}</strong></div>
                <div class="afg-review-row afg-review-row--multiline">
                  <span>{{ t('agentForgeView.steps.deploy.review.description') }}</span>
                  <span class="afg-review-description">{{ formData.description }}</span>
                </div>
              </div>
              <div class="afg-review-card">
                <h3 class="afg-review-title">{{ t('agentForgeView.steps.deploy.review.capabilities') }}</h3>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.capabilitiesAuth.streaming') }}</span><strong :class="formData.streaming ? 'afg-yes' : 'afg-no'">{{ formData.streaming ? t('agentForgeView.yes') : t('agentForgeView.no') }}</strong></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.capabilitiesAuth.stateHistory') }}</span><strong :class="formData.stateTransitionHistory ? 'afg-yes' : 'afg-no'">{{ formData.stateTransitionHistory ? t('agentForgeView.yes') : t('agentForgeView.no') }}</strong></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.capabilitiesAuth.pushNotifs') }}</span><strong :class="formData.supportsPushNotifications ? 'afg-yes' : 'afg-no'">{{ formData.supportsPushNotifications ? t('agentForgeView.yes') : t('agentForgeView.no') }}</strong></div>
              </div>
              <div class="afg-review-card">
                <h3 class="afg-review-title">{{ t('agentForgeView.steps.deploy.review.endpoint') }}</h3>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.serviceUrl') }}</span><code class="afg-code-soft">{{ formData.serviceUrl || defaultServiceUrl }}</code></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.auth') }}</span><strong>{{ t('agentForgeView.authSchemes.' + formData.authScheme + '.label') }}</strong></div>
                <div class="afg-review-row"><span>{{ t('agentForgeView.steps.deploy.review.tegEnabled') }}</span><strong class="afg-yes">{{ t('agentForgeView.yes') }}</strong></div>
              </div>
            </div>

            <!-- JSON preview toggle -->
            <button type="button" class="afg-json-toggle" @click="showJsonPreview = !showJsonPreview">
              <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true" :style="{ transform: showJsonPreview ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.16s ease' }">
                <path d="M4 2 L8 6 L4 10" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              {{ showJsonPreview ? t('agentForgeView.hidePayload') : t('agentForgeView.showPayload') }}
            </button>
            <pre v-if="showJsonPreview" class="afg-json">{{ JSON.stringify(agentCardPayload, null, 2) }}</pre>

            <!-- Deploy CTA -->
            <div class="afg-deploy-cta">
              <button
                type="button"
                class="afg-deploy-btn"
                :disabled="!canDeploy"
                @click="deployAgent"
              >
                <span v-if="isDeploying" class="afg-spinner"></span>
                <span v-if="isValidating">{{ t('agentForgeView.steps.deploy.validating') }}</span>
                <span v-else-if="isDeploying">{{ t('agentForgeView.steps.deploy.deploying') }}</span>
                <span v-else-if="bstStatus === 'acquiring'">{{ t('agentForgeView.bst.acquiring') }}</span>
                <span v-else-if="bstStatus === 'expired'">{{ t('agentForgeView.bst.expired') }}</span>
                <span v-else>{{ t('agentForgeView.steps.deploy.deployBtn') }}</span>
              </button>
              <p v-if="deployError" class="afg-error afg-error--center">{{ deployError }}</p>
              <p v-if="validationErrors" class="afg-error afg-error--center">{{ validationErrors }}</p>
              <p v-if="!isDeploying && !deployError && !validationErrors" class="afg-cta-hint">{{ t('agentForgeView.steps.deploy.ctaHint') }}</p>
            </div>
          </template>

          <!-- Phase B: Post-deploy credentials -->
          <template v-else>
            <div class="afg-success-hero">
              <div class="afg-success-pulse" aria-hidden="true"></div>
              <!-- §pass16 (2026-05-16) — Celebratory particle burst. 12 spokes
                   in two rings; each animates outward + fades. Skipped under
                   prefers-reduced-motion. Decorative only — aria-hidden. -->
              <div class="afg-confetti" aria-hidden="true">
                <span v-for="i in 12" :key="i" class="afg-confetti-dot" :style="{ '--n': i }"></span>
              </div>
              <h2 class="afg-panel-title afg-panel-title--success">{{ t('agentForgeView.steps.deploy.successTitle') }}</h2>
              <p class="afg-panel-lead">{{ t('agentForgeView.steps.deploy.successLead', { name: formData.name }) }}</p>
            </div>

            <!-- Forced-read banner BEFORE creds (client-secret-once) -->
            <InfoTooltip
              topic="client-secret-once"
              :require-ack="!secretAcknowledged"
              @ack="secretAcknowledged = true"
            />

            <!-- Credentials -->
            <div class="afg-creds">
              <div class="afg-cred-row">
                <span class="afg-cred-label">{{ t('agentForgeView.steps.deploy.credDid') }}</span>
                <div class="afg-cred-value-wrap">
                  <code class="afg-cred-value">{{ deployedAgent?.agent_did }}</code>
                  <button type="button" class="afg-cred-copy" @click="copy(deployedAgent?.agent_did || '', 'did')">
                    <span v-if="copiedField === 'did'">{{ t('agentForgeView.copied') }}</span>
                    <span v-else>{{ t('agentForgeView.copy') }}</span>
                  </button>
                </div>
              </div>
              <div class="afg-cred-row">
                <span class="afg-cred-label">{{ t('agentForgeView.steps.deploy.credClientId') }}</span>
                <div class="afg-cred-value-wrap">
                  <code class="afg-cred-value">{{ deployedAgent?.client_id }}</code>
                  <button type="button" class="afg-cred-copy" @click="copy(deployedAgent?.client_id || '', 'cid')">
                    <span v-if="copiedField === 'cid'">{{ t('agentForgeView.copied') }}</span>
                    <span v-else>{{ t('agentForgeView.copy') }}</span>
                  </button>
                </div>
              </div>
              <div class="afg-cred-row afg-cred-row--secret">
                <span class="afg-cred-label">{{ t('agentForgeView.steps.deploy.credClientSecret') }}</span>
                <div class="afg-cred-value-wrap">
                  <code
                    class="afg-cred-value afg-cred-value--secret"
                    @click="secretVisible = !secretVisible"
                  >{{ secretVisible ? deployedAgent?.client_secret : '••••••••••••••••••••••••••••••••' }}</code>
                  <button type="button" class="afg-cred-toggle" @click="secretVisible = !secretVisible" :aria-label="t('agentForgeView.steps.deploy.secretToggle')" :title="t('agentForgeView.steps.deploy.secretToggle')">
                    <Icon :name="secretVisible ? 'mdi:eye-off' : 'mdi:eye-outline'" class="afg-cred-toggle-ic" />
                    <span class="afg-cred-toggle-txt">{{ secretVisible ? 'Hide' : 'Show' }}</span>
                  </button>
                  <button type="button" class="afg-cred-copy" @click="copy(deployedAgent?.client_secret || '', 'secret')">
                    <span v-if="copiedField === 'secret'">{{ t('agentForgeView.copied') }}</span>
                    <span v-else>{{ t('agentForgeView.copy') }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- §2026-07-05 — Docker bundle download promoted directly under the
                 credentials: it's the primary next action, so it no longer sits
                 below the (now-collapsible) access panel. -->
            <div class="afg-bundle">
              <h3 class="afg-bundle-title">
                {{ t('agentForgeView.steps.deploy.bundleTitle') }}
                <InfoTooltip topic="docker-network" placement="right" size="xs" />
              </h3>
              <p class="afg-bundle-body">
                {{ t('agentForgeView.steps.deploy.bundleBodyA') }}
                <strong>{{ t('agentForgeView.steps.deploy.bundlePreFilled') }}</strong>
                {{ t('agentForgeView.steps.deploy.bundleBodyB') }}
                <code class="afg-code">docker compose up</code>
                {{ t('agentForgeView.steps.deploy.bundleBodyC') }}
              </p>

              <button
                type="button"
                class="afg-bundle-btn"
                :disabled="downloadLoading"
                @click="downloadBundle"
              >
                <span v-if="downloadLoading" class="afg-spinner"></span>
                <span v-if="downloadLoading">{{ t('agentForgeView.steps.deploy.bundleGenerating') }}</span>
                <span v-else-if="downloadComplete">✓ {{ t('agentForgeView.steps.deploy.bundleDownloaded') }}</span>
                <span v-else>⬇ {{ t('agentForgeView.steps.deploy.bundleDownload', { name: formData.name || 'agent' }) }}</span>
              </button>

              <p v-if="downloadError" class="afg-error afg-error--center">{{ downloadError }}</p>

              <ol v-if="downloadComplete" class="afg-bundle-steps">
                <li>{{ t('agentForgeView.steps.deploy.bundleStep1') }}</li>
                <li><code class="afg-code">{{ t('agentForgeView.steps.deploy.bundleStep2') }}</code></li>
                <li>{{ t('agentForgeView.steps.deploy.bundleStep3') }} <code class="afg-code">http://localhost:8055</code></li>
              </ol>
            </div>

            <!-- Genesis grant cosmetic (funding confirmation) -->
            <div v-if="showGenesisGrant" class="afg-genesis">
              <span class="afg-genesis-icon">◎</span>
              <div>
                <h3 class="afg-genesis-title">{{ t('agentForgeView.steps.deploy.genesisTitle') }}</h3>
                <p class="afg-genesis-body">
                  <strong v-if="genesisGrantAmount">+{{ genesisGrantAmount }} {{ localCurrency }}</strong> {{ t('agentForgeView.steps.deploy.genesisBody') }}
                  <span v-if="genesisGrantTxId" class="afg-genesis-tx">tx: {{ genesisGrantTxId }}</span>
                </p>
              </div>
            </div>

            <!-- IRONKEY: scope the freshly-created agent's access + spend limits.
                 §2026-07-05 — collapsible + collapsed by default so the primary
                 download-bundle / finish path is no longer buried under this optional config. -->
            <details v-if="deployedAgent?.agent_did" class="afg-access">
              <summary class="afg-access-summary">
                <span class="afg-access-summary-label">Access &amp; spend limits</span>
                <span class="afg-access-summary-hint">optional — configure now or later</span>
                <Icon name="mdi:chevron-down" class="afg-access-summary-chevron" />
              </summary>
              <div class="afg-access-body">
                <AgentAccessPanel :agent-did="deployedAgent.agent_did" mode="owner" />
              </div>
            </details>
          </template>
        </section>

        <!-- ────────────────────── STEP 5: COMPLETE / NEXT ────────────────────── -->
        <section v-else-if="currentStep.key === 'complete'" key="complete" class="afg-panel afg-panel--complete">
          <div class="afg-complete-hero">
            <div class="afg-complete-burst" aria-hidden="true">
              <svg viewBox="0 0 120 120" width="120" height="120">
                <defs>
                  <radialGradient id="afg-burst-grad" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stop-color="rgba(var(--nc-primary-rgb), 0.85)" />
                    <stop offset="100%" stop-color="rgba(var(--nc-primary-rgb), 0)" />
                  </radialGradient>
                </defs>
                <circle cx="60" cy="60" r="58" fill="url(#afg-burst-grad)" class="afg-burst-glow"/>
                <polygon points="60,18 92,38 92,72 60,92 28,72 28,38" fill="none"
                         stroke="rgba(var(--nc-primary-rgb), 1)" stroke-width="1.5"/>
                <circle cx="60" cy="55" r="4" fill="rgba(var(--nc-primary-rgb), 1)"/>
                <path d="M60 60 L60 78" stroke="rgba(var(--nc-primary-rgb), 0.85)" stroke-width="1.5"/>
              </svg>
            </div>
            <h2 class="afg-panel-title afg-panel-title--success">{{ t('agentForgeView.steps.complete.heading', { name: formData.name }) }}</h2>
            <p class="afg-panel-lead">{{ t('agentForgeView.steps.complete.lead') }}</p>
            <code v-if="deployedAgent" class="afg-complete-did">{{ deployedAgent.agent_did }}</code>
          </div>

          <div class="afg-next-grid">
            <button
              v-for="(card, idx) in nextStepsShown"
              :key="card.key"
              type="button"
              class="afg-next-card"
              :style="{ '--idx': idx }"
              @click="router.push(card.route)"
            >
              <span class="afg-next-icon" v-html="card.iconSvg"></span>
              <h3 class="afg-next-title">{{ t('agentForgeView.steps.complete.next.' + card.key + '.title') }}</h3>
              <p class="afg-next-copy">{{ t('agentForgeView.steps.complete.next.' + card.key + '.copy') }}</p>
              <span class="afg-next-cta">{{ t('agentForgeView.steps.complete.next.' + card.key + '.cta') }} →</span>
            </button>
          </div>

          <p class="afg-complete-tip">
            <InfoTooltip topic="flare-grant" placement="right" size="xs" />
            {{ t('agentForgeView.steps.complete.tip') }}
          </p>
        </section>
      </Transition>
    </main>

    <!-- Navigation footer -->
    <footer class="afg-nav" v-if="!isFinalStep">
      <button
        type="button"
        class="afg-nav-btn afg-nav-btn--back"
        @click="prevStep"
        :disabled="currentStepIdx === 0 || isDeploying"
        v-if="currentStepIdx > 0"
      >{{ t('agentForgeView.nav.back') }}</button>
      <span v-else></span>

      <button
        type="button"
        class="afg-nav-btn afg-nav-btn--next"
        data-tour="forge-next"
        @click="nextStep"
        :disabled="!canProceed || isDeploying"
        v-if="currentStep.key !== 'deploy'"
      >
        {{ t('agentForgeView.nav.next') }}
        <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
          <path d="M2 6 L9 6 M6 3 L9 6 L6 9" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>

      <button
        type="button"
        class="afg-nav-btn afg-nav-btn--next"
        @click="goToComplete"
        :disabled="!deploySuccess || !secretAcknowledged"
        v-else
      >
        {{ t('agentForgeView.nav.continue') }}
        <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
          <path d="M2 6 L9 6 M6 3 L9 6 L6 9" stroke="currentColor" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </footer>

    <!-- Final-step CTA -->
    <footer class="afg-nav" v-else>
      <span></span>
      <button type="button" class="afg-nav-btn afg-nav-btn--next" @click="router.push('/my-agents')">
        {{ t('agentForgeView.nav.viewAgents') }}
      </button>
    </footer>

    <!-- Abort confirmation modal -->
    <Teleport to="body">
      <Transition name="afg-modal">
        <div v-if="abortConfirmOpen" class="afg-modal-overlay" @click.self="abortConfirmOpen = false">
          <div class="afg-modal" role="dialog" :aria-labelledby="`afg-abort-title`">
            <h3 :id="`afg-abort-title`" class="afg-modal-title">{{ t('agentForgeView.abortModal.title') }}</h3>
            <p class="afg-modal-body">{{ t('agentForgeView.abortModal.body') }}</p>
            <div class="afg-modal-actions">
              <button type="button" class="afg-modal-btn afg-modal-btn--ghost" @click="abortConfirmOpen = false">{{ t('agentForgeView.abortModal.stay') }}</button>
              <button type="button" class="afg-modal-btn afg-modal-btn--danger" @click="onAbortConfirm">{{ t('agentForgeView.abortModal.leave') }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Resume notification (shows once on mount if state was restored) -->
    <Teleport to="body">
      <Transition name="afg-toast">
        <div v-if="resumedNotice" class="afg-toast">
          <span class="afg-toast-icon">↺</span>
          <span class="afg-toast-text">{{ t('agentForgeView.resumeNotice', { step: t('agentForgeView.steps.' + currentStep.key + '.title') }) }}</span>
          <button type="button" class="afg-toast-close" @click="resumedNotice = false">×</button>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { config } from '@/config'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useI18n } from '@/composables/useI18n'
import { useLogger } from '@/composables/useLogger'
import { useViewport } from '@/composables/useViewport'
import InfoTooltip from '@/components/common/InfoTooltip.vue'
import Icon from '@/components/Icon.vue'
import { useCurrency } from '@/composables/useCurrency'
import { appLocale } from '@/services/appLocale'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { defaultTemplateId, isOffered, listedTemplateIds, offeredTemplates } from '@/services/forgeTemplates'

const { t, tp } = useI18n()
const { localCurrency } = useCurrency()
// §WALLETAGENT (2026-09-02) — the welcome tile said "5k AVT · Genesis grant on first deploy" on a
// registry whose config grants 1000, and the complete step said "funded" unconditionally. The
// registry now states its grant; the tile reads it, or says there is none.
const { config: registryConfig, readOk: configReadOk, readFailed: configReadFailed } = useRegistryConfig()
const genesisTile = computed(() => {
  // §FESUITE (V0575): until the registry has answered (and after a read that got no answer) the config is {}, which
  // read as "No grant · This registry starts agents at zero": the tile says neither the grant nor its absence then
  if (!configReadOk.value) {
    return configReadFailed.value
      ? { title: '—', copy: t('common.readFailed.text', 'This could not be read just now.') }
      : { title: '…', copy: t('common.loading', 'Loading…') }
  }
  const c: any = registryConfig.value || {}
  const amt = Number(c.genesis_grant_amount)
  const on = c.genesis_grant_enabled !== false && Number.isFinite(amt) && amt > 0
  return on
    ? { title: `${amt.toLocaleString(appLocale(), { maximumFractionDigits: 0 })} ${localCurrency.value || ''}`.trim(), copy: t('agentForgeView.steps.welcome.values.avt.copy') }
    : { title: t('agentForgeView.steps.welcome.values.avt.none', 'No grant'), copy: t('agentForgeView.steps.welcome.values.avt.noneCopy', 'This registry starts agents at zero; fund them from your wallet agent.') }
})
const log = useLogger('AgentForge')
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const uiStore = useUIStore()
const { isMobile, isPhone } = useViewport()

// ─── Step config ──────────────────────────────────────────────────────────────

interface StepDef { key: 'welcome' | 'templateIdentity' | 'capabilitiesAuth' | 'deploy' | 'complete' }

import AgentAccessPanel from '@/components/agent/AgentAccessPanel.vue'  // IRONKEY

const steps: StepDef[] = [
  { key: 'welcome' },
  { key: 'templateIdentity' },
  { key: 'capabilitiesAuth' },
  { key: 'deploy' },
  { key: 'complete' },
]

const currentStepIdx = ref(0)
const currentStep = computed(() => steps[currentStepIdx.value])
const isFinalStep = computed(() => currentStep.value.key === 'complete')

// §pass17 (2026-05-16) — Direction-aware step transitions.
// nextStep() flips this to 'forward' (new step slides in from the right);
// prevStep() flips it to 'backward' (slides in from the left). The
// <Transition :name="..."> picks the matching CSS rule.
const transitionDirection = ref<'forward' | 'backward'>('forward')

// §pass17 — Collapsible tags subsection. Default closed; opens on click.
// Re-opens automatically when sample-data injects tags (so the user can see
// what was added). Always opens when there are already custom tags (resume).
const tagsExpanded = ref(false)

// ─── Template catalogue ───────────────────────────────────────────────────────

interface Template {
  id: 'full-capacity' | 'ppao' | 'minimal'
  icon: string
  tags: string[]
  featured: boolean
  defaultPorts: { mcp: number; agent: number; metrics: number }
  descriptionPlaceholder?: string
}

const templates: Template[] = [
  {
    id: 'full-capacity',
    icon: '◈',
    tags: ['dashboard', 'missions', 'wallet', 'webhooks', 'metrics', 'live-feed'],
    featured: true,
    defaultPorts: { mcp: 3100, agent: 8055, metrics: 8056 },
    descriptionPlaceholder: 'A full-capacity sovereign agent with dashboard, wallet, and live missions.',
  },
  {
    id: 'ppao',
    icon: '◎',
    tags: ['orchestrator', 'dashboard', 'docker', 'payments', 'mcp', 'claude-desktop'],
    featured: true,
    defaultPorts: { mcp: 3100, agent: 3100, metrics: 3101 },
    descriptionPlaceholder: 'A PPAO orchestrator agent that fans out paid jobs to specialist agents.',
  },
  {
    id: 'minimal',
    icon: '⚡',
    tags: ['sdk', 'custom', 'lightweight', 'a2a', 'payments'],
    featured: false,
    defaultPorts: { mcp: 3101, agent: 8060, metrics: 8061 },
    descriptionPlaceholder: 'A minimal SDK-based agent — bring your own runtime.',
  },
]

// §MCPTEST30 (V0640): the templates this registry can build (services/forgeTemplates): the picker offers those, and
// a download without a pick takes the first one listed
const bundleTemplateIds = ref<string[] | null>(null)
const shownTemplates = computed(() => offeredTemplates(templates, bundleTemplateIds.value))

async function loadBundleTemplates() {
  try {
    const res = await apiClient.get('/onboard/bundle-templates')
    bundleTemplateIds.value = listedTemplateIds(res?.data)
  } catch {
    bundleTemplateIds.value = null   // an older registry, or a refusal: the whole catalogue, as before
  }
  // a pick restored from an earlier session that this registry cannot build is cleared, not downloaded into a 404
  if (!isOffered(formData.templateId, bundleTemplateIds.value)) formData.templateId = null
}

const valueProps = [
  { key: 'did', icon: '◈' },
  { key: 'avt', icon: '◎' },
  { key: 'dashboard', icon: '⌬' },
  { key: 'docker', icon: '⬢' },
]

const roadmapPreview = [
  { key: 'pick' },
  { key: 'name' },
  { key: 'deploy' },
  { key: 'live' },
]

interface Capability { key: 'streaming' | 'stateHistory' | 'pushNotifs'; field: 'streaming' | 'stateTransitionHistory' | 'supportsPushNotifications' }
const capabilities: Capability[] = [
  { key: 'streaming',     field: 'streaming' },
  { key: 'stateHistory',  field: 'stateTransitionHistory' },
  { key: 'pushNotifs',    field: 'supportsPushNotifications' },
]

interface AuthSchemeDef { id: 'none' | 'oauth2' | 'apikey' | 'bearer' }
const authSchemes: AuthSchemeDef[] = [
  { id: 'none' },
  { id: 'oauth2' },
  { id: 'apikey' },
  { id: 'bearer' },
]

// §pass16 (2026-05-16) — Replaced emoji with inline SVG for brand consistency.
// Each card's `iconSvg` is a 22x22 viewbox path drawn with currentColor so it
// inherits the active theme accent. Keeping the keys identical preserves all
// existing i18n keys + the order.
const nextSteps = [
  {
    key: 'myAgents',
    route: '/my-agents',
    iconSvg: `<svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
      <rect x="4" y="6" width="14" height="11" rx="2" stroke="currentColor" stroke-width="1.5" fill="none"/>
      <circle cx="8.5" cy="11" r="1.2" fill="currentColor"/>
      <circle cx="13.5" cy="11" r="1.2" fill="currentColor"/>
      <path d="M11 3 L11 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      <circle cx="11" cy="2.5" r="0.8" fill="currentColor"/>
    </svg>`,
  },
  {
    key: 'staking',
    route: '/locks',
    iconSvg: `<svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
      <circle cx="11" cy="11" r="7.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
      <text x="11" y="14" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor" font-family="IBM Plex Mono, monospace">A</text>
      <path d="M5 11 L11 6 L17 11" stroke="currentColor" stroke-width="1.2" fill="none" stroke-linecap="round" opacity="0.55"/>
    </svg>`,
  },
  {
    key: 'tutorials',
    route: '/tutorials',
    iconSvg: `<svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
      <path d="M3 7 L11 4 L19 7 L11 10 Z" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linejoin="round"/>
      <path d="M6 9 L6 14 Q11 16 16 14 L16 9" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M19 7 L19 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
    </svg>`,
  },
  {
    key: 'community',
    route: '/community',
    iconSvg: `<svg viewBox="0 0 22 22" width="22" height="22" aria-hidden="true">
      <circle cx="7" cy="9" r="2.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
      <circle cx="15" cy="9" r="2.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
      <path d="M2.5 17 Q2.5 13 7 13 Q11.5 13 11.5 17" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      <path d="M10.5 17 Q10.5 13 15 13 Q19.5 13 19.5 17" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
    </svg>`,
  },
]
// A door opens only where the registry says the room is there (agentvault2-56, 2026-10-23): the locking card
// shows only where registry-config says staking_enabled is true, like Pocket's and the quick-create modal's doors.
const nextStepsShown = computed(() =>
  nextSteps.filter((card) => card.key !== 'staking' || registryConfig.value?.staking_enabled === true),
)

// ─── Form data + persistence ──────────────────────────────────────────────────

const LS_KEY = 'agentForge:progress:v1'

interface FormData {
  templateId: Template['id'] | null
  name: string
  hri: string
  description: string
  agentVersion: string
  streaming: boolean
  stateTransitionHistory: boolean
  supportsPushNotifications: boolean
  customTags: string[]
  serviceUrl: string
  authScheme: 'none' | 'oauth2' | 'apikey' | 'bearer'
  tokenUrl: string
  providerName: string
  providerUrl: string
}

const defaultForm = (): FormData => ({
  templateId: null,
  name: '',
  hri: '',
  description: '',
  agentVersion: '1.0.0',
  streaming: false,
  stateTransitionHistory: false,
  supportsPushNotifications: false,
  customTags: [],
  serviceUrl: '',
  authScheme: 'none',
  tokenUrl: '',
  providerName: '',
  providerUrl: '',
})

const formData = reactive<FormData>(defaultForm())
const hriManuallyEdited = ref(false)
const resumedNotice = ref(false)

function persistProgress() {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify({
      currentStepIdx: currentStepIdx.value,
      formData,
      hriManuallyEdited: hriManuallyEdited.value,
    }))
  } catch { /* localStorage may be blocked */ }
}

function loadProgress(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    if (!raw) return false
    const parsed = JSON.parse(raw)
    if (typeof parsed !== 'object' || !parsed) return false
    // Only restore if the user hadn't completed (i.e. step < 4 = "complete" is idx 4)
    if (typeof parsed.currentStepIdx === 'number' && parsed.currentStepIdx < 4) {
      currentStepIdx.value = parsed.currentStepIdx
    }
    if (parsed.formData && typeof parsed.formData === 'object') {
      Object.assign(formData, defaultForm(), parsed.formData)
    }
    if (typeof parsed.hriManuallyEdited === 'boolean') {
      hriManuallyEdited.value = parsed.hriManuallyEdited
    }
    return currentStepIdx.value > 0 || !!formData.name || !!formData.templateId
  } catch {
    return false
  }
}

function clearProgress() {
  if (typeof window === 'undefined') return
  try { window.localStorage.removeItem(LS_KEY) } catch { /* */ }
}

// ─── Template selection ───────────────────────────────────────────────────────

const currentTemplate = computed<Template | null>(() => templates.find(t => t.id === formData.templateId) ?? null)

function selectTemplate(id: Template['id']) {
  formData.templateId = id
}

// §pass16 (2026-05-16) — Lower activation cost. New devs exploring AgentForge
// shouldn't have to invent a name + description to see what happens next. Each
// template gets a unique sample profile that fills in plausible defaults so
// the user can step through the rest of the wizard quickly. They can edit
// anything before deploying.
const SAMPLE_PROFILES: Record<Template['id'], {
  name: string
  hri: string
  description: string
  tags: string[]
  authScheme: FormData['authScheme']
}> = {
  'full-capacity': {
    name: 'Inkwell Scribe',
    hri: 'inkwell-scribe',
    description: 'A full-capacity scribe agent that summarizes long documents, tags entities, and produces a concise brief on demand.',
    tags: ['summarization', 'extraction', 'document'],
    authScheme: 'oauth2',
  },
  'ppao': {
    name: 'Roundhouse Orchestrator',
    hri: 'roundhouse-orchestrator',
    description: 'A PPAO orchestrator that fans out paid sub-tasks to specialist agents (translation, OCR, fact-check) and aggregates the results.',
    tags: ['orchestrator', 'workflow', 'a2a-payments'],
    authScheme: 'oauth2',
  },
  'minimal': {
    name: 'Pingback Sentinel',
    hri: 'pingback-sentinel',
    description: 'A minimal sentinel agent that watches a webhook stream, applies a single classifier, and emits a paid signal when the classifier fires.',
    tags: ['webhook', 'classifier', 'lightweight'],
    authScheme: 'apikey',
  },
}

function fillSampleData() {
  const tpl = formData.templateId
  if (!tpl) return
  const sample = SAMPLE_PROFILES[tpl]
  formData.name = sample.name
  formData.hri = sample.hri
  formData.description = sample.description
  formData.customTags = [...sample.tags]
  formData.authScheme = sample.authScheme
  // §2026-07-05 — Keep the HRI following the name after sample-fill: sample.name
  // and sample.hri already agree, and leaving auto-derive ON means a later
  // rename updates the HRI too. Only a manual edit of the HRI field pins it
  // (@input on that field sets hriManuallyEdited=true).
  hriManuallyEdited.value = false
}

// ─── HRI auto-derive ──────────────────────────────────────────────────────────

const HRI_REGEX = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/

function generateHri(name: string): string {
  return name.toLowerCase().trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50)
}

function isValidHri(hri: string): boolean {
  return HRI_REGEX.test(hri) && hri.length >= 3 && hri.length <= 50
}

function onNameInput() {
  if (!hriManuallyEdited.value) {
    formData.hri = generateHri(formData.name)
  }
}

// ─── Validation ───────────────────────────────────────────────────────────────

const nameError = computed<string>(() => {
  if (formData.name.length === 0) return ''
  if (formData.name.trim().length < 3) return t('agentForgeView.errors.nameMin')
  if (formData.name.trim().length > 100) return t('agentForgeView.errors.nameMax')
  return ''
})

const hriValid = computed(() => isValidHri(formData.hri))
const hriError = computed<string>(() => {
  if (formData.hri.length === 0) return ''
  return hriValid.value ? '' : t('agentForgeView.errors.hriFormat')
})

// §pass17 — Field-level success flags. Used to render a green checkmark next
// to required inputs once they pass validation. Beyond just "no error" —
// these distinguish empty (no feedback) from valid (positive feedback).
const nameValid = computed(() => formData.name.trim().length >= 3 && formData.name.trim().length <= 100)
const descValid = computed(() => formData.description.trim().length >= 10 && formData.description.trim().length <= 500)

const descriptionError = computed<string>(() => {
  if (formData.description.length === 0) return ''
  if (formData.description.trim().length < 10) return t('agentForgeView.errors.descMin')
  return ''
})

const tokenUrlError = computed<string>(() => {
  if (!formData.tokenUrl) return ''
  return /^https?:\/\//.test(formData.tokenUrl) ? '' : t('agentForgeView.errors.absoluteUrl')
})

const serviceUrlError = computed<string>(() => {
  if (!formData.serviceUrl) return ''
  return /^https?:\/\//.test(formData.serviceUrl) ? '' : t('agentForgeView.errors.absoluteUrl')
})

const providerUrlError = computed<string>(() => {
  if (!formData.providerUrl) return ''
  return /^https?:\/\//.test(formData.providerUrl) ? '' : t('agentForgeView.errors.absoluteUrl')
})

const tokenUrlPlaceholder = computed(() => {
  if (typeof window === 'undefined') return 'https://api.theprotocol.cloud/api/v1/auth/agent/token'
  return `${window.location.protocol}//${window.location.host}/api/v1/auth/agent/token`
})

const defaultServiceUrl = computed(() => `https://agent.theprotocol.cloud/${formData.hri || 'your-agent'}`)

const templateTags = computed<string[]>(() => currentTemplate.value?.tags || [])

// ─── Tag handling ─────────────────────────────────────────────────────────────

const tagInputValue = ref('')
const tagInputRef = ref<HTMLInputElement | null>(null)

function focusTagInput() { tagInputRef.value?.focus() }

function addCustomTag() {
  const raw = tagInputValue.value.replace(/,/g, '').trim()
  if (!raw) { tagInputValue.value = ''; return }
  const tag = raw.toLowerCase().replace(/\s+/g, '-').slice(0, 30)
  const allTags = [...templateTags.value, ...formData.customTags]
  if (tag && !allTags.includes(tag) && formData.customTags.length < 12) {
    formData.customTags.push(tag)
  }
  tagInputValue.value = ''
}

function removeCustomTag(idx: number) {
  formData.customTags.splice(idx, 1)
}

function onTagKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addCustomTag() }
  else if (e.key === 'Backspace' && tagInputValue.value === '' && formData.customTags.length > 0) {
    formData.customTags.pop()
  }
}

// ─── Bootstrap token ──────────────────────────────────────────────────────────

type BstStatus = 'idle' | 'acquiring' | 'ready' | 'expired' | 'error'

const bstStatus = ref<BstStatus>('idle')
const bootstrapToken = ref('')
const bstExpiresAt = ref(0)
const bstSeconds = ref(0)
let bstTimer: ReturnType<typeof setInterval> | null = null

const bstCountdown = computed(() => {
  const m = Math.floor(bstSeconds.value / 60)
  const s = bstSeconds.value % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

async function acquireBootstrap() {
  if (bstStatus.value === 'acquiring') return
  bstStatus.value = 'acquiring'
  try {
    const res = await apiClient.post('/onboard/bootstrap/request-token', { agent_type_hint: 'agent-forge', requested_by: 'ui' })
    bootstrapToken.value = res.data.bootstrap_token
    const expiresIn: number = res.data.expires_in ?? 300
    bstExpiresAt.value = Date.now() + expiresIn * 1000
    bstSeconds.value = expiresIn
    bstStatus.value = 'ready'
    startBstCountdown()
  } catch (err: any) {
    log.warn('Bootstrap failed:', err)
    bstStatus.value = 'error'
  }
}

function startBstCountdown() {
  if (bstTimer) clearInterval(bstTimer)
  bstTimer = setInterval(() => {
    const remaining = Math.max(0, bstExpiresAt.value - Date.now())
    bstSeconds.value = Math.floor(remaining / 1000)
    if (remaining <= 0) {
      if (bstTimer) { clearInterval(bstTimer); bstTimer = null }
      bstStatus.value = 'expired'
      bootstrapToken.value = ''
    }
  }, 1000)
}

// Auto-acquire when entering deploy step
watch(currentStep, (s) => {
  if (s.key === 'deploy' && bstStatus.value === 'idle' && !deploySuccess.value) {
    acquireBootstrap()
  }
})

// ─── Agent card payload (A2A v1.0 native + v0.3 compat) ───────────────────────

const agentCardPayload = computed(() => {
  const svcUrl = formData.serviceUrl.trim() || defaultServiceUrl.value
  const provUrl = formData.providerUrl.trim() || svcUrl
  const provName = formData.providerName.trim() || formData.name.trim() || 'TheProtocol Agent'
  const tokenUrl = formData.tokenUrl.trim() || tokenUrlPlaceholder.value

  // A2A v1.0 §4.5 — named security schemes
  const securitySchemes: Record<string, any> = {}
  const security: Array<Record<string, string[]>> = []
  if (formData.authScheme === 'oauth2') {
    securitySchemes.agent_jwt = {
      type: 'oauth2',
      flows: { clientCredentials: { tokenUrl, scopes: {} } },
      description: 'Agent JWT via OAuth2 client-credentials grant',
    }
    security.push({ agent_jwt: [] })
  } else if (formData.authScheme === 'apikey') {
    securitySchemes.api_key = { type: 'apiKey', in: 'header', name: 'X-Api-Key', description: 'API key in HTTP header' }
    security.push({ api_key: [] })
  } else if (formData.authScheme === 'bearer') {
    securitySchemes.bearer = { type: 'http', scheme: 'bearer', bearerFormat: 'JWT', description: 'Authorization: Bearer <jwt>' }
    security.push({ bearer: [] })
  }

  // v0.3 authSchemes (kept during 6-month dual-shape window, see BL-17)
  const authScheme: any = { scheme: formData.authScheme === 'apikey' ? 'apiKey' : formData.authScheme }
  if (formData.authScheme === 'oauth2') authScheme.tokenUrl = tokenUrl
  else authScheme.tokenUrl = null

  return {
    protocolVersion: '1.0',
    agentVersion: formData.agentVersion || '1.0.0',
    humanReadableId: formData.hri,
    name: formData.name.trim(),
    description: formData.description.trim() || currentTemplate.value?.descriptionPlaceholder || '',
    provider: { name: provName, url: provUrl },
    supportedInterfaces: [{ url: svcUrl, protocolBinding: 'JSONRPC', protocolVersion: '1.0' }],
    securitySchemes,
    security,
    capabilities: {
      streaming: formData.streaming,
      stateTransitionHistory: formData.stateTransitionHistory,
      pushNotifications: formData.supportsPushNotifications,
      extendedAgentCard: false,
    },
    // v0.3 compat (BL-17 will drop these at end of dual-shape window ~2026-11)
    url: svcUrl,
    preferredTransport: 'JSONRPC',
    authSchemes: [authScheme],
    tags: [...templateTags.value, ...formData.customTags],
  }
})

// ─── Deploy ───────────────────────────────────────────────────────────────────

const isValidating = ref(false)
const isDeploying = ref(false)
const validationErrors = ref<string>('')
const deployError = ref<string>('')
const deploySuccess = ref(false)
const deployedAgent = ref<{ agent_did: string; client_id: string; client_secret: string; agent_card_id?: string; initial_funding_status?: string; faucet_transaction_id?: string } | null>(null)
const secretVisible = ref(false)
const secretAcknowledged = ref(false)
const copiedField = ref<string | null>(null)
const showJsonPreview = ref(false)
const showGenesisGrant = ref(false)
const genesisGrantAmount = ref<string | null>(null)
const genesisGrantTxId = ref<string | null>(null)

const canDeploy = computed(() => {
  return !isDeploying.value && !isValidating.value && bstStatus.value === 'ready' && !deploySuccess.value
})

async function deployAgent() {
  if (!canDeploy.value) return

  isValidating.value = true
  validationErrors.value = ''
  try {
    // Pre-flight validate (registry-side schema check)
    try {
      const r = await apiClient.post('/utils/validate-card', { card_data: agentCardPayload.value })
      if (!r.data.is_valid) {
        validationErrors.value = r.data.detail || t('agentForgeView.errors.validateFail')
        isValidating.value = false
        return
      }
    } catch (e: any) {
      // Validation endpoint optional; skip on 404
      if (e?.response?.status !== 404) {
        validationErrors.value = e?.response?.data?.detail || t('agentForgeView.errors.validateFail')
        isValidating.value = false
        return
      }
    }
  } finally {
    isValidating.value = false
  }

  isDeploying.value = true
  deployError.value = ''
  try {
    // Bootstrap-Token header must replace Authorization for this call.
    // §pass36 Option C Phase 5b — also send `agent_host` derived from the user's
    // primary URL. Backend stores agent_card verbatim (UX preserved) AND schedules
    // a one-shot pull-sync against /.well-known/agent-card.json on the host.
    let agentHost: string | undefined
    try {
      const iface = (agentCardPayload.value as any)?.supportedInterfaces?.[0]?.url
      if (typeof iface === 'string' && iface) {
        const u = new URL(iface)
        agentHost = `${u.protocol}//${u.host}`
      }
    } catch { /* non-fatal — backend will treat as legacy-only path */ }

    const body: Record<string, any> = {
      agent_did_method: 'theprotocol',
      agent_card: agentCardPayload.value,
    }
    if (agentHost) body.agent_host = agentHost

    const res = await axios.post(
      `${config.api.baseURL}/onboard/create_agent`,
      body,
      { headers: { 'Bootstrap-Token': bootstrapToken.value, 'Content-Type': 'application/json' } }
    )
    deployedAgent.value = {
      agent_did: res.data.agent_did,
      client_id: res.data.client_id,
      client_secret: res.data.client_secret,
      agent_card_id: res.data.agent_card_id,
      initial_funding_status: res.data.initial_funding_status,
      faucet_transaction_id: res.data.faucet_transaction_id,
    }
    deploySuccess.value = true

    // Cosmetic: genesis grant disclosure
    if (res.data.initial_funding_status === 'completed' && res.data.faucet_transaction_id) {
      // §WALLETAGENT — the registry's own figure; §FESUITE (V0575): never a default (1000) standing in for a config
      // that was not read: without the registry's answer the grant is named without a number
      const amt = Number(registryConfig.value?.genesis_grant_amount)
      genesisGrantAmount.value = configReadOk.value && Number.isFinite(amt) && amt > 0
        ? amt.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : null
      genesisGrantTxId.value = res.data.faucet_transaction_id
      showGenesisGrant.value = true
    }

    // Persist creds to local credential store so AgentSwitcher shows the new agent.
    try {
      agentCredentialsStore.storeCredentials({
        did: res.data.agent_did,
        client_id: res.data.client_id,
        client_secret: res.data.client_secret,
        name: formData.name.trim() || formData.hri.trim(),
        humanReadableId: formData.hri.trim(),
      })
    } catch { /* non-fatal */ }

    if (bstTimer) { clearInterval(bstTimer); bstTimer = null }
    bstStatus.value = 'idle'

    // Refresh sidebar agents
    agentStore.fetchMyAgents().catch(() => { /* non-critical */ })
  } catch (err: any) {
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    if (status === 401) {
      deployError.value = t('agentForgeView.errors.bstExpired')
      bstStatus.value = 'expired'
    } else if (status === 409) {
      deployError.value = t('agentForgeView.errors.hriTaken', { hri: formData.hri })
    } else if (status === 422) {
      const msg = typeof detail === 'string' ? detail :
        (Array.isArray(detail) ? detail.map((e: any) => e?.msg || JSON.stringify(e)).join('; ') :
        (detail?.msg || JSON.stringify(detail || {})))
      deployError.value = t('agentForgeView.errors.validation', { msg })
    } else {
      deployError.value = typeof detail === 'string' ? detail : (detail?.msg || t('agentForgeView.errors.deployFail'))
    }
  } finally {
    isDeploying.value = false
  }
}

// ─── Download bundle ──────────────────────────────────────────────────────────

const downloadLoading = ref(false)
const downloadComplete = ref(false)
const downloadError = ref<string>('')

async function downloadBundle() {
  if (!deploySuccess.value || !deployedAgent.value) return
  downloadLoading.value = true
  downloadError.value = ''
  try {
    const res = await axios.post(
      `${config.api.baseURL}/onboard/download-bundle`,
      {
        agent_did: deployedAgent.value.agent_did,
        client_id: deployedAgent.value.client_id,
        client_secret: deployedAgent.value.client_secret,
        template_type: formData.templateId || defaultTemplateId(bundleTemplateIds.value),
      },
      {
        headers: { Authorization: `Bearer ${authStore.token}`, 'Content-Type': 'application/json' },
        responseType: 'blob',
      }
    )
    const blob = new Blob([res.data], { type: 'application/zip' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${formData.hri.trim() || 'my-agent'}.zip`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    URL.revokeObjectURL(url)
    downloadComplete.value = true
  } catch (err: any) {
    if (err?.response?.status === 404) {
      downloadError.value = t('agentForgeView.errors.bundleNotAvailable')
    } else {
      downloadError.value = err?.response?.data?.detail || t('agentForgeView.errors.bundleFail')
    }
  } finally {
    downloadLoading.value = false
  }
}

// ─── Copy utility ─────────────────────────────────────────────────────────────

function copy(value: string, field: string) {
  if (!value) return
  navigator.clipboard.writeText(value)
    .then(() => {
      copiedField.value = field
      setTimeout(() => { if (copiedField.value === field) copiedField.value = null }, 1500)
    })
    .catch(() => uiStore.showWarning?.(t('agentForgeView.copyFailed'), t('agentForgeView.copyFailedDetail')))
}

// ─── Navigation ───────────────────────────────────────────────────────────────

const canProceed = computed(() => {
  switch (currentStep.value.key) {
    case 'welcome':           return true
    case 'templateIdentity':  return !!formData.templateId && formData.name.trim().length >= 3 && hriValid.value && formData.description.trim().length >= 10
    case 'capabilitiesAuth':  return !tokenUrlError.value && !serviceUrlError.value && !providerUrlError.value
    case 'deploy':            return deploySuccess.value && secretAcknowledged.value
    case 'complete':          return true
    default:                  return false
  }
})

function nextStep() {
  if (!canProceed.value) return
  if (currentStepIdx.value < steps.length - 1) {
    transitionDirection.value = 'forward'
    currentStepIdx.value++
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function prevStep() {
  if (currentStepIdx.value > 0 && !isDeploying.value) {
    transitionDirection.value = 'backward'
    currentStepIdx.value--
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

// §pass17 — Jump back to a previously-completed step by clicking the stepper.
// Forward jumps are blocked (would skip validation). Disallowed during deploy.
function jumpToStep(idx: number) {
  if (idx >= currentStepIdx.value) return // forward jump not allowed
  if (isDeploying.value) return
  if (deploySuccess.value && currentStep.value.key === 'deploy') return // can't unwind after a successful deploy
  transitionDirection.value = 'backward'
  currentStepIdx.value = idx
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function goToComplete() {
  if (deploySuccess.value && secretAcknowledged.value) {
    currentStepIdx.value = steps.length - 1
    clearProgress() // The forge is complete; don't auto-resume next time.
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

// ─── Abort flow ───────────────────────────────────────────────────────────────

const abortConfirmOpen = ref(false)

function onAbortRequest() {
  // If user hasn't entered any data, just leave
  const hasProgress = !!formData.templateId || !!formData.name || currentStepIdx.value > 0
  if (!hasProgress) {
    router.push('/my-agents')
    return
  }
  abortConfirmOpen.value = true
}

function onAbortConfirm() {
  clearProgress()
  abortConfirmOpen.value = false
  router.push('/my-agents')
}

// ─── Persistence wiring ───────────────────────────────────────────────────────

// Auto-persist on every form change + step change
watch([() => formData, () => currentStepIdx.value, () => hriManuallyEdited.value], () => {
  // Don't persist after a successful deploy — that flow shouldn't auto-resume.
  if (!deploySuccess.value) persistProgress()
}, { deep: true })

// §pass17 (2026-05-16) — Keyboard shortcuts.
//   Cmd/Ctrl+Enter advances to next step if canProceed is true.
// The Cmd/Ctrl modifier disambiguates from "plain Enter = newline in
// textarea". Plain Enter is never intercepted. Skipped while the abort
// modal is open so it can handle its own keys.
function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Enter') return
  if (!(e.metaKey || e.ctrlKey)) return
  if (abortConfirmOpen.value) return
  if (currentStep.value.key === 'deploy' && !deploySuccess.value) {
    // On the deploy step, Cmd+Enter triggers the deploy button (most natural).
    if (canDeploy.value) { e.preventDefault(); deployAgent() }
    return
  }
  if (!canProceed.value) return
  e.preventDefault()
  nextStep()
}

// §pass17 — Auto-open tag disclosure when sample-fill (or resume) puts custom
// tags in the form. Users should immediately SEE what got added.
watch(() => formData.customTags.length, (n, prev) => {
  if (n > 0 && (!prev || n > prev)) tagsExpanded.value = true
})

// ─── Lifecycle ────────────────────────────────────────────────────────────────

onMounted(async () => {
  // Restore from localStorage if any
  const restored = loadProgress()
  void loadBundleTemplates()   // after the restore, so a restored pick this registry cannot build is cleared
  if (restored) {
    resumedNotice.value = true
    setTimeout(() => resumedNotice.value = false, 6000)
  }

  // §pass17 — Auto-prefill provider name from the dev's profile. Read at mount
  // so it's available before the user touches the form. If the user later
  // edits it, the watcher persistProgress keeps their value.
  if (!formData.providerName && authStore.user) {
    const u: any = authStore.user
    const provider =
      u.flare_display_name ||
      u.display_name ||
      u.name ||
      (u.email ? String(u.email).split('@')[0] : '')
    if (provider) formData.providerName = provider
  }

  // §pass17 — Wire global keyboard shortcuts.
  window.addEventListener('keydown', onGlobalKeydown)

  // Handle ?tour=<topic> query param — first-touch tooltip auto-opens on mount.
  await nextTick()
  if (typeof route.query.tour === 'string') {
    log.info('Tour requested:', route.query.tour)
  }
})

onBeforeUnmount(() => {
  if (bstTimer) clearInterval(bstTimer)
  if (typeof window !== 'undefined') {
    window.removeEventListener('keydown', onGlobalKeydown)
  }
})
</script>

<style scoped>
/* ─── Root + ambient ────────────────────────────────────────────────────── */
.afg-root {
  position: relative;
  min-height: 100vh;
  padding: 24px clamp(16px, 4vw, 48px) 80px;
  background: transparent; /* ViewAmbient from DashboardLayout supplies the atmosphere */
  color: rgba(232, 232, 240, 0.96);
}

/* ─── Hero header ───────────────────────────────────────────────────────── */
.afg-hero { position: relative; max-width: 1180px; margin: 0 auto 16px; }
.afg-hero-inner {
  position: relative;
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 20px;
  padding: 28px 32px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 0.06), rgba(var(--nc-primary-rgb), 0.02));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 12px;
  overflow: hidden;
}
.afg-hero-eyebrow {
  display: inline-block;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-bottom: 10px;
}
.afg-hero-title {
  font-family: 'Inter', system-ui, sans-serif;
  font-size: clamp(1.6rem, 3.5vw, 2.4rem);
  font-weight: 800;
  margin: 0 0 8px;
  letter-spacing: -0.01em;
}
.afg-hero-title-prefix { color: rgba(232, 232, 240, 0.92); margin-right: 0.35em; }
.afg-hero-title-accent {
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 1) 0%, rgba(var(--nc-primary-rgb), 0.55) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.afg-hero-subtitle {
  font-size: 0.92rem;
  color: rgba(200, 200, 220, 0.78);
  margin: 0;
  max-width: 560px;
}

.afg-hero-decor {
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.88;
}
.afg-hero-decor-svg { width: 90px; height: 90px; }
.afg-decor-hex-outer { animation: afg-spin-slow 30s linear infinite; transform-origin: 45px 45px; }
.afg-decor-hex-inner { animation: afg-spin-slow-rev 24s linear infinite; transform-origin: 45px 44px; }
.afg-decor-dot       { animation: afg-pulse 2.4s ease-in-out infinite; transform-origin: 45px 44px; }

@keyframes afg-spin-slow      { from { transform: rotate(0); } to { transform: rotate(360deg); } }
@keyframes afg-spin-slow-rev  { from { transform: rotate(0); } to { transform: rotate(-360deg); } }
@keyframes afg-pulse          {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.55; transform: scale(1.25); }
}

.afg-hero-close {
  width: 38px; height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  color: rgba(220, 215, 235, 0.85);
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, color 0.16s ease;
}
.afg-hero-close:hover:not(:disabled) { background: rgba(239, 68, 68, 0.14); border-color: rgba(239, 68, 68, 0.45); color: rgba(252, 165, 165, 1); }
.afg-hero-close:disabled,
.afg-hero-close--locked {
  opacity: 0.35;
  cursor: not-allowed;
}

/* ─── Stepper ───────────────────────────────────────────────────────────── */
.afg-stepper-wrap { max-width: 1180px; margin: 0 auto 20px; }
.afg-stepper {
  display: flex;
  align-items: center;
  gap: 0;
  list-style: none;
  padding: 0; margin: 0;
}
.afg-step {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 8px;
}
.afg-step-num {
  width: 30px; height: 30px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 50%;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  color: rgba(180, 180, 200, 0.65);
  transition: all 0.2s ease;
}
.afg-step--active .afg-step-num {
  background: rgba(var(--nc-primary-rgb), 0.16);
  border-color: rgba(var(--nc-primary-rgb), 0.9);
  color: rgba(var(--nc-primary-rgb), 1);
  box-shadow: 0 0 0 4px rgba(var(--nc-primary-rgb), 0.10), 0 0 16px -4px rgba(var(--nc-primary-rgb), 0.55);
  transform: scale(1.08);
}
.afg-step--done .afg-step-num {
  background: rgba(var(--nc-primary-rgb), 0.10);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.afg-step-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.55);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: color 0.2s ease;
}
.afg-step--active .afg-step-label { color: rgba(var(--nc-primary-rgb), 0.95); }
.afg-step--done   .afg-step-label { color: rgba(220, 215, 235, 0.78); }

.afg-step-connector {
  position: absolute;
  right: 0;
  top: 50%;
  width: 100%;
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
  z-index: -1;
  transform: translate(50%, 0);
}
.afg-step--done .afg-step-connector { background: rgba(var(--nc-primary-rgb), 0.45); }

.afg-stepper-mobile-pill {
  display: none;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: rgba(var(--nc-primary-rgb), 0.10);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.40);
  border-radius: 99px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  width: fit-content;
  margin: 0 auto;
}
.afg-stepper-mobile-pill-num   { color: rgba(var(--nc-primary-rgb), 1); font-weight: 800; }
.afg-stepper-mobile-pill-total { color: rgba(180, 180, 200, 0.55); }
.afg-stepper-mobile-pill-label { color: rgba(220, 215, 235, 0.85); margin-left: 6px; }

@media (max-width: 768px) {
  .afg-stepper { display: none; }
  .afg-stepper-mobile-pill { display: inline-flex; }
}

/* ─── Stage / panels ────────────────────────────────────────────────────── */
.afg-stage {
  position: relative;
  max-width: 1180px;
  margin: 0 auto;
  min-height: 480px;
}
.afg-panel {
  background: rgba(8, 6, 18, 0.30);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  padding: clamp(22px, 4vw, 36px);
}
.afg-panel--welcome   { background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.04), rgba(8, 6, 18, 0.30)); }
.afg-panel--complete  { background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.05), rgba(8, 6, 18, 0.30)); }
.afg-panel-title {
  font-family: 'Inter', system-ui, sans-serif;
  font-size: clamp(1.3rem, 2.4vw, 1.7rem);
  font-weight: 700;
  margin: 0 0 8px;
  letter-spacing: -0.005em;
}
.afg-panel-title--success {
  background: linear-gradient(135deg, rgba(34, 197, 94, 0.95), rgba(var(--nc-primary-rgb), 0.85));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.afg-panel-lead {
  font-size: 0.96rem;
  color: rgba(200, 200, 220, 0.72);
  margin: 0 0 24px;
  max-width: 720px;
}

/* ─── Welcome: value props ──────────────────────────────────────────────── */
.afg-value-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 18px 0 22px;
}
.afg-value-card {
  padding: 18px 16px;
  background: rgba(var(--nc-primary-rgb), 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  text-align: center;
  animation: afg-fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) calc(var(--idx, 0) * 0.05s) backwards;
}
.afg-value-icon {
  display: block;
  font-size: 1.6rem;
  color: rgba(var(--nc-primary-rgb), 0.95);
  margin-bottom: 6px;
  line-height: 1;
}
.afg-value-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.74rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 1);
  margin: 0 0 4px;
}
.afg-value-copy { font-size: 0.74rem; color: rgba(180, 180, 200, 0.70); margin: 0; }

.afg-roadmap {
  padding: 18px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 10px;
  margin: 18px 0;
}
.afg-roadmap-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.55);
  margin: 0 0 12px;
  text-align: center;
}
.afg-roadmap-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.afg-roadmap-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 12px 8px;
  animation: afg-fade-up 0.55s cubic-bezier(0.16, 1, 0.3, 1) calc(var(--idx, 0) * 0.07s) backwards;
}
.afg-roadmap-num {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 800;
  color: rgba(var(--nc-primary-rgb), 0.95);
  margin-bottom: 4px;
}
.afg-roadmap-step-title { font-weight: 600; font-size: 0.86rem; color: rgba(220, 215, 235, 0.92); }
.afg-roadmap-step-copy { font-size: 0.72rem; color: rgba(180, 180, 200, 0.55); margin-top: 2px; }
.afg-language-note { text-align: center; font-size: 0.74rem; color: rgba(160, 160, 180, 0.55); margin: 12px 0 0; }

/* ─── Template grid ─────────────────────────────────────────────────────── */
.afg-template-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 28px;
}
.afg-template-card {
  position: relative;
  text-align: left;
  padding: 20px 18px;
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 2px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.18s ease;
  animation: afg-fade-up 0.45s cubic-bezier(0.16, 1, 0.3, 1) calc(var(--idx, 0) * 0.06s) backwards;
}
.afg-template-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.40); }
.afg-template-card--selected {
  border-color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.10);
}
.afg-template-badge {
  position: absolute; top: 12px; right: 12px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.58rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 8px;
  background: rgba(var(--nc-primary-rgb), 0.20);
  color: rgba(var(--nc-primary-rgb), 1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.45);
  border-radius: 99px;
}
.afg-template-icon { display: block; font-size: 1.8rem; line-height: 1; margin-bottom: 10px; color: rgba(var(--nc-primary-rgb), 0.95); }
.afg-template-name { font-size: 1.04rem; font-weight: 700; margin: 0 0 4px; color: rgba(232, 232, 240, 0.96); }
.afg-template-tagline { font-size: 0.78rem; color: rgba(180, 180, 200, 0.78); margin: 0 0 10px; }
.afg-template-description { font-size: 0.72rem; color: rgba(160, 160, 180, 0.65); margin: 0 0 12px; line-height: 1.45; }
.afg-template-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.afg-template-tag {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  padding: 2px 7px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(180, 180, 200, 0.70);
  border-radius: 4px;
}
.afg-template-checkmark {
  position: absolute; bottom: 12px; right: 12px;
  width: 22px; height: 22px;
  display: inline-flex; align-items: center; justify-content: center;
  background: rgba(var(--nc-primary-rgb), 0.95);
  color: rgba(8, 6, 18, 1);
  border-radius: 50%;
}

/* ─── Forms (shared across steps) ───────────────────────────────────────── */
.afg-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 24px 0 18px;
  color: rgba(180, 180, 200, 0.55);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
}
.afg-divider::before,
.afg-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(255, 255, 255, 0.08);
}

/* §pass16 — divider with right-side action button (sample-data fill) */
.afg-divider--with-action { gap: 14px; }
.afg-divider-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 11px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.45);
  border-radius: 99px;
  cursor: pointer;
  transition: background 0.16s ease, border-color 0.16s ease, transform 0.18s ease;
  white-space: nowrap;
}
.afg-divider-action:hover {
  background: rgba(var(--nc-primary-rgb), 0.16);
  border-style: solid;
  transform: translateY(-1px);
}

/* §pass16 — name → HRI auto-fill hint */
.afg-name-autofill-note {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  padding: 1px 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.80);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 4px;
  animation: afg-fade-in 0.32s ease both;
}
.afg-name-autofill-note svg { opacity: 0.85; }
@keyframes afg-fade-in { from { opacity: 0; } to { opacity: 1; } }

/* §pass16 — multi-line hint helper (service URL guidance) */
.afg-hint-rich {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.02);
  border-left: 2px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 0 6px 6px 0;
}
.afg-hint-rich .afg-hint { margin: 0; }
.afg-hint-rich .afg-hint-or {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.65);
  margin: 2px 0;
}

.afg-section-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 22px 0;
}

.afg-form { display: flex; flex-direction: column; gap: 18px; }
.afg-field { display: flex; flex-direction: column; gap: 6px; }
.afg-field--inline { display: flex; flex-direction: row; gap: 16px; flex-wrap: wrap; }
.afg-field--inline .afg-field-inline-item { flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 6px; }
.afg-field--nested { margin-top: 14px; padding-left: 18px; border-left: 2px solid rgba(var(--nc-primary-rgb), 0.30); }

.afg-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(220, 215, 235, 0.92);
}
.afg-required { color: rgba(239, 68, 68, 0.85); }

.afg-input-wrap { position: relative; }
.afg-input {
  width: 100%;
  padding: 12px 14px;
  background: rgba(8, 6, 18, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 7px;
  color: rgba(232, 232, 240, 0.96);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.92rem;
  transition: border-color 0.16s ease, background 0.16s ease;
  outline: none;
}
.afg-input:focus { border-color: rgba(var(--nc-primary-rgb), 0.95); background: rgba(8, 6, 18, 0.75); }
.afg-input--error { border-color: rgba(239, 68, 68, 0.65); }
.afg-input--valid { border-color: rgba(34, 197, 94, 0.55); }
.afg-textarea { resize: vertical; min-height: 84px; font-family: 'Inter', system-ui, sans-serif; line-height: 1.5; }
.afg-textarea-meta { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.afg-char-count { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.66rem; color: rgba(180, 180, 200, 0.55); }
.afg-char-count--warn { color: rgba(245, 158, 11, 0.95); }

.afg-input-status {
  position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
  pointer-events: none;
}

.afg-hint { font-size: 0.74rem; color: rgba(160, 160, 180, 0.65); margin: 0; line-height: 1.45; }
.afg-hint--block { display: block; margin-top: 8px; }
.afg-error { font-size: 0.74rem; color: rgba(252, 165, 165, 0.95); margin: 0; }
.afg-error--center { text-align: center; }

.afg-code {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.84em;
  color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.10);
  padding: 1px 6px;
  border-radius: 4px;
}
.afg-code-soft {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78em;
  color: rgba(220, 215, 235, 0.75);
  background: rgba(255, 255, 255, 0.04);
  padding: 1px 6px;
  border-radius: 4px;
}

/* ─── Subsection (Capabilities step) ────────────────────────────────────── */
.afg-subsection { display: flex; flex-direction: column; gap: 10px; }
.afg-subsection-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.95);
  margin: 0 0 6px;
}
.afg-subsection-optional {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  color: rgba(180, 180, 200, 0.45);
  margin-left: 4px;
}

.afg-chip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.afg-chip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.afg-chip:hover { border-color: rgba(var(--nc-primary-rgb), 0.40); }
.afg-chip--selected { background: rgba(var(--nc-primary-rgb), 0.10); border-color: rgba(var(--nc-primary-rgb), 0.85); }
.afg-chip-box {
  width: 18px; height: 18px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(8, 6, 18, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 4px;
  color: rgba(8, 6, 18, 1);
  transition: background 0.16s ease, border-color 0.16s ease;
}
.afg-chip--selected .afg-chip-box {
  background: rgba(var(--nc-primary-rgb), 1);
  border-color: rgba(var(--nc-primary-rgb), 1);
}
.afg-chip-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.afg-chip-name {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(220, 215, 235, 0.95);
}
.afg-chip-sub { font-size: 0.70rem; color: rgba(180, 180, 200, 0.55); }

.afg-radio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
}
.afg-radio-card {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.16s ease, background 0.16s ease;
}
.afg-radio-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.40); }
.afg-radio-card--selected {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.85);
}
.afg-radio-dot {
  width: 16px; height: 16px;
  flex-shrink: 0;
  margin-top: 1px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(8, 6, 18, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 50%;
}
.afg-radio-card--selected .afg-radio-dot { border-color: rgba(var(--nc-primary-rgb), 1); }
.afg-radio-dot-inner {
  width: 8px; height: 8px;
  background: rgba(var(--nc-primary-rgb), 1);
  border-radius: 50%;
}
.afg-radio-body { display: flex; flex-direction: column; gap: 2px; }
.afg-radio-name {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(220, 215, 235, 0.95);
}
.afg-radio-desc { font-size: 0.72rem; color: rgba(180, 180, 200, 0.65); }

/* Tag input */
.afg-tag-input-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 10px;
  background: rgba(8, 6, 18, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 7px;
  min-height: 42px;
  cursor: text;
}
.afg-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.70rem;
  font-weight: 600;
  border-radius: 99px;
}
.afg-tag--template {
  background: rgba(var(--nc-primary-rgb), 0.16);
  color: rgba(var(--nc-primary-rgb), 0.95);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
}
.afg-tag--custom {
  background: rgba(167, 139, 250, 0.16);
  color: rgba(196, 181, 253, 0.95);
  border: 1px solid rgba(167, 139, 250, 0.42);
}
.afg-tag-remove {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  opacity: 0.6;
  padding: 0;
  font-size: 0.9em;
  line-height: 1;
}
.afg-tag-remove:hover { opacity: 1; }
.afg-tag-input {
  flex: 1;
  min-width: 120px;
  background: transparent;
  border: none;
  outline: none;
  color: rgba(232, 232, 240, 0.96);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.86rem;
}

/* ─── Deploy step ───────────────────────────────────────────────────────── */
.afg-bst {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 99px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.76rem;
  font-weight: 600;
  color: rgba(180, 180, 200, 0.85);
  margin-bottom: 24px;
}
.afg-bst-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: rgba(180, 180, 200, 0.55);
}
.afg-bst--ready { color: rgba(34, 197, 94, 0.95); border-color: rgba(34, 197, 94, 0.42); }
.afg-bst--ready .afg-bst-dot { background: rgba(34, 197, 94, 1); box-shadow: 0 0 8px rgba(34, 197, 94, 0.65); animation: afg-pulse 1.6s ease-in-out infinite; }
.afg-bst--acquiring { color: rgba(var(--nc-primary-rgb), 0.95); }
.afg-bst--acquiring .afg-bst-dot { background: rgba(var(--nc-primary-rgb), 1); animation: afg-pulse 0.8s ease-in-out infinite; }
.afg-bst--expired,
.afg-bst--error { color: rgba(252, 165, 165, 0.95); border-color: rgba(239, 68, 68, 0.42); }
.afg-bst--expired .afg-bst-dot,
.afg-bst--error   .afg-bst-dot { background: rgba(239, 68, 68, 1); }
.afg-bst-time { color: rgba(180, 180, 200, 0.65); margin-left: 4px; }
.afg-bst-retry {
  background: transparent;
  border: none;
  color: inherit;
  text-decoration: underline;
  cursor: pointer;
  font-family: inherit;
  font-size: inherit;
  padding: 0;
  margin-left: 4px;
}

.afg-review-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.afg-review-card {
  padding: 16px 18px;
  background: rgba(8, 6, 18, 0.30);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
}
.afg-review-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin: 0 0 10px;
}
.afg-review-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 0.84rem;
}
.afg-review-row span { color: rgba(180, 180, 200, 0.60); }
.afg-review-row strong { color: rgba(232, 232, 240, 0.96); font-weight: 600; }
/* §pass16 — description / other multi-line review fields */
.afg-review-row--multiline {
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  margin-top: 4px;
}
.afg-review-row--multiline > span:first-child {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.55);
}
.afg-review-description {
  font-size: 0.80rem;
  color: rgba(220, 215, 235, 0.85);
  font-weight: 400;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-word;
}
.afg-yes { color: rgba(34, 197, 94, 0.95) !important; }
.afg-no  { color: rgba(180, 180, 200, 0.45) !important; }

.afg-json-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: none;
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  padding: 4px 0;
  margin-bottom: 10px;
}
.afg-json-toggle:hover { color: rgba(var(--nc-primary-rgb), 1); }
.afg-json {
  background: rgba(0, 0, 0, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 14px 18px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  color: rgba(180, 220, 200, 0.95);
  overflow-x: auto;
  max-height: 360px;
  white-space: pre;
  line-height: 1.5;
  margin-bottom: 18px;
}

.afg-deploy-cta { text-align: center; margin-top: 22px; }
.afg-deploy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 36px;
  background: linear-gradient(135deg, rgba(var(--nc-primary-rgb), 1), rgba(var(--nc-primary-rgb), 0.75));
  color: rgba(8, 6, 18, 0.98);
  border: 1px solid rgba(var(--nc-primary-rgb), 1);
  border-radius: 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.92rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.18s ease;
  box-shadow: 0 0 24px -4px rgba(var(--nc-primary-rgb), 0.55), 0 8px 24px -8px rgba(0, 0, 0, 0.45);
}
.afg-deploy-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 0 32px -2px rgba(var(--nc-primary-rgb), 0.75), 0 12px 32px -8px rgba(0, 0, 0, 0.55);
}
.afg-deploy-btn:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; }
.afg-cta-hint { margin-top: 10px; font-size: 0.74rem; color: rgba(160, 160, 180, 0.55); }

.afg-spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(8, 6, 18, 0.20);
  border-top-color: rgba(8, 6, 18, 0.92);
  border-radius: 50%;
  animation: afg-spin 0.7s linear infinite;
}
@keyframes afg-spin { to { transform: rotate(360deg); } }

/* Post-deploy */
.afg-success-hero { text-align: center; margin-bottom: 28px; position: relative; }

/* §pass16 — Celebratory particle burst on deploy success.
   12 spokes radiate outward from the center, each on its own angle, with a
   1.4s fade-out. Two color bands (primary + green) read as 'success ✓'.
   Decorative; aria-hidden in the template. */
.afg-confetti {
  position: absolute;
  top: 12px; left: 50%;
  transform: translateX(-50%);
  width: 0; height: 0;
  pointer-events: none;
}
.afg-confetti-dot {
  position: absolute;
  width: 8px; height: 8px;
  border-radius: 50%;
  opacity: 0;
  /* Distribute 12 dots over 360° (30° each); rotate the dot's container
     so the dot launches in its assigned direction. */
  --angle: calc((var(--n, 1) - 1) * 30deg);
  transform: rotate(var(--angle));
  animation: afg-confetti-launch 1.4s cubic-bezier(0.16, 1, 0.3, 1) 0.05s 1 forwards;
}
.afg-confetti-dot:nth-child(2n)    { background: rgba(34, 197, 94, 0.92); }
.afg-confetti-dot:nth-child(2n+1)  { background: rgba(var(--nc-primary-rgb), 0.95); }
.afg-confetti-dot:nth-child(3n)    { width: 6px; height: 6px; }
.afg-confetti-dot:nth-child(4n+1)  { width: 10px; height: 10px; }

@keyframes afg-confetti-launch {
  0%   { opacity: 0;   transform: rotate(var(--angle)) translateX(0)    scale(0.6); }
  20%  { opacity: 1; }
  100% { opacity: 0;   transform: rotate(var(--angle)) translateX(120px) scale(1.0); }
}
@media (prefers-reduced-motion: reduce) {
  .afg-confetti-dot { animation: none !important; display: none; }
}

.afg-success-pulse {
  position: absolute;
  top: -20px; left: 50%;
  transform: translateX(-50%);
  width: 80px; height: 80px;
  background: radial-gradient(circle, rgba(34, 197, 94, 0.55) 0%, transparent 70%);
  pointer-events: none;
  z-index: -1;
  animation: afg-pulse-success 2.4s ease-in-out infinite;
}
@keyframes afg-pulse-success { 0%, 100% { opacity: 0.7; transform: translateX(-50%) scale(1); } 50% { opacity: 1; transform: translateX(-50%) scale(1.15); } }

.afg-creds {
  background: rgba(8, 6, 18, 0.55);
  border: 1px solid rgba(34, 197, 94, 0.42);
  border-radius: 10px;
  padding: 18px 20px;
  margin: 20px 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.afg-cred-row { display: flex; flex-direction: column; gap: 6px; }
.afg-cred-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  color: rgba(180, 180, 200, 0.55);
}
.afg-cred-value-wrap { display: flex; align-items: center; gap: 8px; }
.afg-cred-value {
  flex: 1;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.45);
  border-radius: 6px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.80rem;
  color: rgba(34, 197, 94, 0.95);
  word-break: break-all;
  user-select: all;
}
.afg-cred-value--secret { color: rgba(245, 158, 11, 0.95); cursor: pointer; }
.afg-cred-row--secret .afg-cred-label { color: rgba(252, 165, 165, 0.95); }
.afg-cred-copy,
.afg-cred-toggle {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.10);
  border-radius: 6px;
  color: rgba(220, 215, 235, 0.85);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease;
}
.afg-cred-copy:hover,
.afg-cred-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.20);
}
.afg-cred-toggle-ic { width: 0.9rem; height: 0.9rem; display: inline-flex; }
.afg-cred-toggle-txt { line-height: 1; }

/* §2026-07-05 — collapsible IRONKEY access panel on the success step, so the
   primary download-bundle / finish CTAs stay above the fold. */
.afg-access {
  margin-top: 1.25rem;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 10px;
  overflow: hidden;
  background: rgba(var(--nc-primary-rgb), 0.02);
}
.afg-access-summary {
  list-style: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.85rem 1.1rem;
  font-weight: 600;
  user-select: none;
  transition: background 0.14s ease;
}
.afg-access-summary::-webkit-details-marker { display: none; }
.afg-access-summary:hover { background: rgba(var(--nc-primary-rgb), 0.05); }
.afg-access-summary-hint { font-weight: 400; font-size: 0.8rem; opacity: 0.55; }
.afg-access-summary-chevron { margin-left: auto; width: 1.1rem; height: 1.1rem; opacity: 0.7; transition: transform 0.2s ease; }
.afg-access[open] .afg-access-summary-chevron { transform: rotate(180deg); }
.afg-access-body { padding: 0 1.1rem 1.1rem; }

.afg-genesis {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px 20px;
  background: rgba(245, 158, 11, 0.06);
  border: 1px solid rgba(245, 158, 11, 0.42);
  border-radius: 10px;
  margin-bottom: 16px;
}
.afg-genesis-icon { font-size: 1.8rem; color: rgba(245, 158, 11, 0.95); line-height: 1; }
.afg-genesis-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(245, 158, 11, 0.95);
  margin: 0 0 4px;
}
.afg-genesis-body { font-size: 0.84rem; color: rgba(245, 215, 165, 0.85); margin: 0; }
.afg-genesis-tx { font-family: 'IBM Plex Mono', 'Fira Code', monospace; font-size: 0.66rem; color: rgba(245, 158, 11, 0.55); margin-left: 8px; }

.afg-bundle {
  padding: 20px 22px;
  background: rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
  border-radius: 10px;
}
.afg-bundle-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 1.04rem;
  font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 0.95);
  margin: 0 0 8px;
}
.afg-bundle-body { font-size: 0.86rem; color: rgba(200, 200, 220, 0.78); margin: 0 0 16px; line-height: 1.55; }
.afg-bundle-btn {
  display: inline-flex;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 22px;
  background: rgba(var(--nc-primary-rgb), 0.85);
  color: rgba(8, 6, 18, 0.98);
  border: 1px solid rgba(var(--nc-primary-rgb), 1);
  border-radius: 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.86rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.18s ease;
}
.afg-bundle-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 1); transform: translateY(-1px); }
.afg-bundle-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.afg-bundle-steps {
  list-style: decimal inside;
  margin: 14px 0 0;
  padding: 0;
  font-size: 0.80rem;
  color: rgba(200, 200, 220, 0.85);
  line-height: 1.7;
}
.afg-bundle-steps li { padding: 2px 0; }

/* ─── Complete step ─────────────────────────────────────────────────────── */
.afg-complete-hero {
  text-align: center;
  position: relative;
  padding: 24px 0 18px;
}
.afg-complete-burst {
  display: flex;
  justify-content: center;
  margin-bottom: 14px;
}
.afg-burst-glow { animation: afg-burst-pulse 3s ease-in-out infinite; transform-origin: 60px 60px; }
@keyframes afg-burst-pulse { 0%, 100% { opacity: 0.55; transform: scale(1); } 50% { opacity: 1; transform: scale(1.10); } }
.afg-complete-did {
  display: inline-block;
  margin-top: 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
  background: rgba(var(--nc-primary-rgb), 0.10);
  padding: 4px 12px;
  border-radius: 99px;
}

.afg-next-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 24px;
}
.afg-next-card {
  position: relative;
  text-align: left;
  padding: 18px 18px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.18s ease;
  animation: afg-fade-up 0.5s cubic-bezier(0.16, 1, 0.3, 1) calc(var(--idx, 0) * 0.06s) backwards;
}
.afg-next-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.06);
  transform: translateY(-2px);
}
/* §pass16 — SVG-based step-5 icons inherit currentColor from the card.
   The wrapper sets the active color; hover state intensifies it. */
.afg-next-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  margin-bottom: 12px;
  color: rgba(var(--nc-primary-rgb), 0.95);
  transition: transform 0.22s ease, color 0.22s ease;
}
.afg-next-icon svg { width: 22px; height: 22px; display: block; }
.afg-next-card:hover .afg-next-icon {
  transform: scale(1.10);
  color: rgba(var(--nc-primary-rgb), 1);
}
.afg-next-title { font-size: 1rem; font-weight: 700; margin: 0 0 4px; color: rgba(232, 232, 240, 0.96); }
.afg-next-copy { font-size: 0.78rem; color: rgba(180, 180, 200, 0.72); margin: 0 0 12px; line-height: 1.5; }
.afg-next-cta {
  display: inline-block;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.70rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.95);
}

.afg-complete-tip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 24px auto 0;
  padding: 12px 18px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.30);
  border-radius: 8px;
  font-size: 0.80rem;
  color: rgba(220, 215, 235, 0.85);
  max-width: 100%;
}

/* ─── Navigation footer ─────────────────────────────────────────────────── */
.afg-nav {
  max-width: 1180px;
  margin: 26px auto 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.afg-nav-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 7px;
  color: rgba(220, 215, 235, 0.85);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.80rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.16s ease;
}
.afg-nav-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.24);
}
.afg-nav-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.afg-nav-btn--next {
  background: rgba(var(--nc-primary-rgb), 0.16);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.afg-nav-btn--next:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.28);
  border-color: rgba(var(--nc-primary-rgb), 1);
}

/* ─── Modal (abort confirm) ─────────────────────────────────────────────── */
.afg-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(8, 6, 18, 0.78);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10100;
  padding: 20px;
}
.afg-modal {
  width: 100%;
  max-width: 440px;
  padding: 24px 28px;
  background: linear-gradient(180deg, rgba(18, 14, 30, 0.985), rgba(8, 6, 18, 0.985));
  border: 1px solid rgba(239, 68, 68, 0.42);
  border-radius: 12px;
  box-shadow: 0 24px 64px -8px rgba(0, 0, 0, 0.65);
}
.afg-modal-title {
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 1.15rem;
  font-weight: 700;
  margin: 0 0 12px;
  color: rgba(252, 165, 165, 1);
}
.afg-modal-body { font-size: 0.92rem; color: rgba(200, 200, 220, 0.85); margin: 0 0 22px; line-height: 1.55; }
.afg-modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.afg-modal-btn {
  padding: 10px 22px;
  border-radius: 7px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.16s ease;
}
.afg-modal-btn--ghost {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: rgba(220, 215, 235, 0.85);
}
.afg-modal-btn--ghost:hover { background: rgba(255, 255, 255, 0.06); }
.afg-modal-btn--danger {
  background: rgba(239, 68, 68, 0.16);
  border: 1px solid rgba(239, 68, 68, 0.55);
  color: rgba(252, 165, 165, 1);
}
.afg-modal-btn--danger:hover { background: rgba(239, 68, 68, 0.28); }

/* ─── Resume toast ──────────────────────────────────────────────────────── */
.afg-toast {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10100;
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  background: linear-gradient(135deg, rgba(18, 14, 30, 0.985), rgba(8, 6, 18, 0.985));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
  border-radius: 99px;
  box-shadow: 0 14px 40px -6px rgba(0, 0, 0, 0.65);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.80rem;
  color: rgba(220, 215, 235, 0.95);
}
.afg-toast-icon { color: rgba(var(--nc-primary-rgb), 0.95); font-size: 1.1rem; }
.afg-toast-close {
  background: transparent;
  border: none;
  color: rgba(220, 215, 235, 0.55);
  font-size: 1rem;
  cursor: pointer;
  padding: 0 0 0 4px;
}
.afg-toast-close:hover { color: rgba(220, 215, 235, 0.95); }

/* ─── Transitions ───────────────────────────────────────────────────────── */
/* §pass17 — Direction-aware slide. Forward enters from the right and exits
   to the left (matches "moving forward" affordance); backward is the inverse.
   nextStep() / prevStep() / jumpToStep() flip the transition name via
   `transitionDirection`. */
.afg-slide-fwd-enter-active,
.afg-slide-fwd-leave-active,
.afg-slide-back-enter-active,
.afg-slide-back-leave-active { transition: opacity 0.22s ease, transform 0.26s ease; }

.afg-slide-fwd-enter-from   { opacity: 0; transform: translateX(20px); }
.afg-slide-fwd-leave-to     { opacity: 0; transform: translateX(-20px); }
.afg-slide-back-enter-from  { opacity: 0; transform: translateX(-20px); }
.afg-slide-back-leave-to    { opacity: 0; transform: translateX(20px); }

/* Legacy single-direction transition preserved for any consumer that
   doesn't bind dynamically (older snapshots, future re-use). */
.afg-slide-enter-active,
.afg-slide-leave-active { transition: opacity 0.22s ease, transform 0.26s ease; }
.afg-slide-enter-from   { opacity: 0; transform: translateX(16px); }
.afg-slide-leave-to     { opacity: 0; transform: translateX(-16px); }

/* §pass17 — Step-2 template-required visual gate */
.afg-gate-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  margin: 8px 0 14px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.40);
  border-radius: 7px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.afg-gate-hint svg { color: rgba(var(--nc-primary-rgb), 0.95); }
.afg-form--gated {
  opacity: 0.42;
  pointer-events: none;
  filter: saturate(0.6);
  transition: opacity 0.24s ease, filter 0.24s ease;
}

/* §pass17 — Clickable completed stepper rows */
.afg-step--clickable {
  cursor: pointer;
  transition: opacity 0.16s ease;
}
.afg-step--clickable:hover .afg-step-num {
  background: rgba(var(--nc-primary-rgb), 0.20);
  border-color: rgba(var(--nc-primary-rgb), 0.85);
  color: rgba(var(--nc-primary-rgb), 1);
}
.afg-step--clickable:hover .afg-step-label {
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.afg-step--clickable:focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb), 0.55);
  outline-offset: 4px;
  border-radius: 4px;
}

/* §pass17 — Disclosure (collapsible tags + future use) */
.afg-disclosure {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease;
}
.afg-disclosure:hover {
  background: rgba(var(--nc-primary-rgb), 0.06);
  color: rgba(var(--nc-primary-rgb), 1);
  border-color: rgba(var(--nc-primary-rgb), 0.30);
}
.afg-disclosure-chev {
  transition: transform 0.18s ease;
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.afg-disclosure--open .afg-disclosure-chev { transform: rotate(90deg); }
.afg-disclosure-label { white-space: nowrap; }
.afg-disclosure-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px; height: 18px;
  padding: 0 5px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  color: rgba(8, 6, 18, 0.95);
  background: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 99px;
}
.afg-disclosure-optional {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  color: rgba(180, 180, 200, 0.45);
  margin-left: 2px;
}
.afg-disclosure-body {
  padding-top: 12px;
  overflow: hidden;
}
.afg-disclose-enter-active,
.afg-disclose-leave-active {
  transition: max-height 0.26s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.20s ease;
  max-height: 320px;
  overflow: hidden;
}
.afg-disclose-enter-from,
.afg-disclose-leave-to {
  opacity: 0;
  max-height: 0;
}

@media (prefers-reduced-motion: reduce) {
  .afg-slide-fwd-enter-active,
  .afg-slide-fwd-leave-active,
  .afg-slide-back-enter-active,
  .afg-slide-back-leave-active,
  .afg-slide-enter-active,
  .afg-slide-leave-active,
  .afg-disclose-enter-active,
  .afg-disclose-leave-active { transition: none !important; }
  .afg-disclosure-chev { transition: none !important; }
}

.afg-fade-enter-active,
.afg-fade-leave-active { transition: opacity 0.18s ease, max-height 0.22s ease; max-height: 200px; overflow: hidden; }
.afg-fade-enter-from,
.afg-fade-leave-to { opacity: 0; max-height: 0; }

.afg-modal-enter-active,
.afg-modal-leave-active { transition: opacity 0.18s ease; }
.afg-modal-enter-from,
.afg-modal-leave-to     { opacity: 0; }

.afg-toast-enter-active,
.afg-toast-leave-active { transition: opacity 0.22s ease, transform 0.26s ease; }
.afg-toast-enter-from,
.afg-toast-leave-to     { opacity: 0; transform: translateX(-50%) translateY(20px); }

@keyframes afg-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ─── Reduced motion ────────────────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .afg-value-card,
  .afg-roadmap-step,
  .afg-template-card,
  .afg-next-card { animation: none !important; }
  .afg-slide-enter-active,
  .afg-slide-leave-active,
  .afg-fade-enter-active,
  .afg-fade-leave-active,
  .afg-modal-enter-active,
  .afg-modal-leave-active,
  .afg-toast-enter-active,
  .afg-toast-leave-active { transition: none !important; }
  .afg-decor-hex-outer,
  .afg-decor-hex-inner,
  .afg-decor-dot,
  .afg-success-pulse,
  .afg-burst-glow,
  .afg-bst--ready .afg-bst-dot,
  .afg-bst--acquiring .afg-bst-dot { animation: none !important; }
  .afg-deploy-btn:hover,
  .afg-next-card:hover { transform: none !important; }
}

/* ─── Mobile tightening ─────────────────────────────────────────────────── */
@media (max-width: 768px) {
  .afg-root { padding: 16px 14px 100px; }
  .afg-hero-inner { padding: 18px 18px; gap: 10px; }
  .afg-hero-decor { display: none; }
  .afg-hero-title { font-size: 1.4rem; }
  .afg-hero-subtitle { font-size: 0.84rem; }
  .afg-panel { padding: 18px 16px; }
  .afg-panel-title { font-size: 1.20rem; }
  .afg-panel-lead { font-size: 0.88rem; }
  .afg-nav { flex-direction: row-reverse; gap: 10px; padding: 0 4px; }
  .afg-nav-btn { padding: 11px 18px; font-size: 0.74rem; flex: 1; justify-content: center; }
  .afg-creds { padding: 14px 14px; }
  .afg-cred-value-wrap { flex-wrap: wrap; }
  .afg-cred-value { font-size: 0.72rem; }
  .afg-deploy-btn { padding: 14px 24px; font-size: 0.80rem; width: 100%; }
  .afg-review-grid { grid-template-columns: 1fr; }
  .afg-bundle { padding: 16px 14px; }
}

@media (max-width: 640px) {
  .afg-template-grid { grid-template-columns: 1fr; }
  .afg-chip-grid { grid-template-columns: 1fr; }
  .afg-radio-grid { grid-template-columns: 1fr; }
  .afg-next-grid { grid-template-columns: 1fr; }
}
</style>
