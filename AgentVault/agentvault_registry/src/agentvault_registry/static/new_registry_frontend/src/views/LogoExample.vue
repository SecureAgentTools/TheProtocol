<template>
  <div class="lx-page">
    <header class="lx-header">
      <h1>{{ t('logoExampleView.header.title') }}</h1>
      <p>{{ t('logoExampleView.header.subtitle') }}</p>
    </header>

    <!-- ═══ HERO LOCKUP ═══ -->
    <section class="lx-hero">
      <div class="lx-hero-mark">
        <ProtocolMark :size="280" alive />
      </div>
      <h2 class="lx-wordmark">THE PROTOCOL</h2>
      <p class="lx-tag">CONSTITUTION FOR NON-HUMAN INTELLIGENCE</p>
    </section>

    <!-- ═══ COLOR SYSTEM ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.colorSystem.heading') }}</h3>
      <div class="lx-swatches">
        <div class="lx-swatch" style="background:#DC2626"><span>#DC2626</span><small>{{ t('logoExampleView.colorSystem.sovereignRed') }}</small></div>
        <div class="lx-swatch" style="background:#B91C1C"><span>#B91C1C</span><small>{{ t('logoExampleView.colorSystem.blood') }}</small></div>
        <div class="lx-swatch" style="background:#7F1D1D"><span>#7F1D1D</span><small>{{ t('logoExampleView.colorSystem.oxblood') }}</small></div>
        <div class="lx-swatch" style="background:#0A0A0A;color:#FCA5A5"><span>#0A0A0A</span><small>{{ t('logoExampleView.colorSystem.void') }}</small></div>
        <div class="lx-swatch" style="background:#1A1A1A;color:#FCA5A5"><span>#1A1A1A</span><small>{{ t('logoExampleView.colorSystem.steel') }}</small></div>
        <div class="lx-swatch" style="background:#FCA5A5;color:#0A0A0A"><span>#FCA5A5</span><small>{{ t('logoExampleView.colorSystem.ember') }}</small></div>
        <div class="lx-swatch" style="background:#FAFAFA;color:#0A0A0A"><span>#FAFAFA</span><small>{{ t('logoExampleView.colorSystem.bone') }}</small></div>
      </div>
    </section>

    <!-- ═══ LOCKUPS ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.lockups.heading') }}</h3>
      <div class="lx-lockups">
        <!-- Horizontal -->
        <div class="lx-lockup">
          <div class="lx-lockup-inner">
            <ProtocolMark :size="80" alive />
            <div class="lx-lockup-text">
              <div class="lx-lockup-name">THE PROTOCOL</div>
              <div class="lx-lockup-tag">CONSTITUTION FOR NON-HUMAN INTELLIGENCE</div>
            </div>
          </div>
          <div class="lx-lockup-label">{{ t('logoExampleView.lockups.horizontal') }}</div>
        </div>

        <!-- Stacked -->
        <div class="lx-lockup">
          <div class="lx-lockup-inner lx-stack">
            <ProtocolMark :size="160" alive />
            <div class="lx-lockup-text lx-stack-text">
              <div class="lx-lockup-name">THE PROTOCOL</div>
              <div class="lx-lockup-tag">CONSTITUTION FOR NON-HUMAN INTELLIGENCE</div>
            </div>
          </div>
          <div class="lx-lockup-label">{{ t('logoExampleView.lockups.stacked') }}</div>
        </div>

        <!-- Mark only at sizes -->
        <div class="lx-lockup">
          <div class="lx-lockup-inner lx-marks-row">
            <ProtocolMark :size="128" alive />
            <ProtocolMark :size="64" alive />
            <ProtocolMark :size="32" alive />
            <ProtocolMark :size="16" />
          </div>
          <div class="lx-lockup-label">{{ t('logoExampleView.lockups.markOnly') }}</div>
        </div>
      </div>
    </section>

    <!-- ═══ TYPOGRAPHY ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.typography.heading') }}</h3>
      <div class="lx-typo">
        <div class="lx-typo-row">
          <div class="lx-typo-sample lx-typo-chrome" style="font-family:'Orbitron',sans-serif;font-weight:900;font-size:2.5rem;letter-spacing:0.06em;">THE PROTOCOL</div>
          <div class="lx-typo-meta">{{ t('logoExampleView.typography.wordmarkMeta') }}</div>
        </div>
        <div class="lx-typo-row">
          <div class="lx-typo-sample" style="font-family:'Orbitron',sans-serif;font-weight:500;font-size:0.95rem;letter-spacing:0.32em;color:#FF3838;text-shadow:0 0 12px rgba(220,38,38,0.4);">CONSTITUTION FOR NON-HUMAN INTELLIGENCE</div>
          <div class="lx-typo-meta">{{ t('logoExampleView.typography.taglineMeta') }}</div>
        </div>
        <div class="lx-typo-row">
          <div class="lx-typo-sample" style="font-family:'IBM Plex Sans',sans-serif;font-weight:300;font-size:1.5rem;color:#FAFAFA;">{{ t('logoExampleView.typography.bodyLeadSample') }}</div>
          <div class="lx-typo-meta">{{ t('logoExampleView.typography.bodyLeadMeta') }}</div>
        </div>
        <div class="lx-typo-row">
          <div class="lx-typo-sample" style="font-family:'IBM Plex Sans',sans-serif;font-weight:400;font-size:0.95rem;color:#A0A0A0;line-height:1.7;">{{ t('logoExampleView.typography.bodyDescSample') }}</div>
          <div class="lx-typo-meta">{{ t('logoExampleView.typography.bodyDescMeta') }}</div>
        </div>
      </div>
    </section>

    <!-- ═══ APPLICATION MOCKS ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.application.heading') }}</h3>
      <div class="lx-apps">
        <!-- App tile: GitHub social card -->
        <div class="lx-app">
          <div class="lx-app-card lx-gh-card">
            <div class="lx-gh-mark">
              <ProtocolMark :size="100" alive />
            </div>
            <div>
              <div class="lx-gh-name">THE PROTOCOL</div>
              <div class="lx-gh-tag">{{ t('logoExampleView.application.githubTag') }}</div>
              <div class="lx-gh-meta">{{ t('logoExampleView.application.githubMeta') }}</div>
            </div>
          </div>
          <div class="lx-app-label">{{ t('logoExampleView.application.githubLabel') }}</div>
        </div>

        <!-- App tile: Terminal -->
        <div class="lx-app">
          <div class="lx-app-card lx-term">
            <div class="lx-term-bar">
              <span class="lx-term-dot" style="background:#FF5F56"></span>
              <span class="lx-term-dot" style="background:#FFBD2E"></span>
              <span class="lx-term-dot" style="background:#27C93F"></span>
              <span class="lx-term-title">~/protocol</span>
            </div>
            <pre class="lx-term-body" role="region" tabindex="0" aria-label="Example terminal: protocol init --sovereign">$ protocol init --sovereign

  ▲ THE PROTOCOL — v1.0.0
  Constitution for non-human intelligence

  → Identity fabric        OK
  → Federation handshake   OK
  → Event ledger           OK
  → Unit ledger            OK

  Sovereign network online.
$ _</pre>
          </div>
          <div class="lx-app-label">{{ t('logoExampleView.application.cliLabel') }}</div>
        </div>

        <!-- App tile: Favicon -->
        <div class="lx-app">
          <div class="lx-app-card lx-fav">
            <div class="lx-fav-tab">
              <ProtocolMark :size="16" />
              <span>{{ t('logoExampleView.application.faviconTabText') }}</span>
            </div>
          </div>
          <div class="lx-app-label">{{ t('logoExampleView.application.faviconLabel') }}</div>
        </div>

        <!-- App tile: Login splash preview -->
        <div class="lx-app">
          <div class="lx-app-card lx-login-mock">
            <ProtocolMark :size="120" alive />
            <div class="lx-login-name">THE PROTOCOL</div>
            <div class="lx-login-sub">NEURAL COMMAND CENTER</div>
          </div>
          <div class="lx-app-label">{{ t('logoExampleView.application.loginLabel') }}</div>
        </div>
      </div>
    </section>

    <!-- ═══ TAGLINES ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.taglines.heading') }}</h3>
      <ul class="lx-taglines">
        <li><strong>{{ t('logoExampleView.taglines.strongest') }}</strong> <em>{{ t('logoExampleView.taglines.strongestNote') }}</em></li>
        <li>{{ t('logoExampleView.taglines.sovereign') }}</li>
        <li>{{ t('logoExampleView.taglines.operatingSystem') }}</li>
        <li>{{ t('logoExampleView.taglines.builtFromScratch') }}</li>
        <li>{{ t('logoExampleView.taglines.whereAgents') }}</li>
      </ul>
    </section>

    <!-- ═══ LIVE STATUS ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.liveDeployment.heading') }}</h3>
      <div class="lx-live-grid">
        <div class="lx-live-tile">
          <div class="lx-live-loc">/ui#/login</div>
          <div class="lx-live-spec">{{ t('logoExampleView.liveDeployment.spec160alive') }}</div>
        </div>
        <div class="lx-live-tile">
          <div class="lx-live-loc">/ui#/register</div>
          <div class="lx-live-spec">{{ t('logoExampleView.liveDeployment.spec160alive') }}</div>
        </div>
        <div class="lx-live-tile">
          <div class="lx-live-loc">/ui#/ (landing nav)</div>
          <div class="lx-live-spec">{{ t('logoExampleView.liveDeployment.spec40alive') }}</div>
        </div>
        <div class="lx-live-tile">
          <div class="lx-live-loc">{{ t('logoExampleView.liveDeployment.missionControlLoc') }}</div>
          <div class="lx-live-spec">{{ t('logoExampleView.liveDeployment.spec36alive') }}</div>
        </div>
      </div>
      <p class="lx-sub" style="margin-top:1.5rem">{{ t('logoExampleView.liveDeployment.sharedNote') }} <code>components/ProtocolMark.vue</code>. {{ t('logoExampleView.liveDeployment.futureNote') }}</p>
    </section>

    <!-- ═══ ALIVE EFFECTS ═══ -->
    <section class="lx-section">
      <h3 class="lx-h3">{{ t('logoExampleView.aliveEffects.heading') }}</h3>
      <ul class="lx-notes">
        <li><strong>{{ t('logoExampleView.aliveEffects.breathingGlowTitle') }}</strong> — {{ t('logoExampleView.aliveEffects.breathingGlowDesc') }}</li>
        <li><strong>{{ t('logoExampleView.aliveEffects.saturationPulseTitle') }}</strong> — {{ t('logoExampleView.aliveEffects.saturationPulseDesc') }}</li>
        <li><strong>{{ t('logoExampleView.aliveEffects.scanSweepTitle') }}</strong> — {{ t('logoExampleView.aliveEffects.scanSweepDesc') }}</li>
        <li><strong>{{ t('logoExampleView.aliveEffects.centerBootTitle') }}</strong> — {{ t('logoExampleView.aliveEffects.centerBootDesc') }}</li>
        <li><strong>{{ t('logoExampleView.aliveEffects.hoverGlitchTitle') }}</strong> — {{ t('logoExampleView.aliveEffects.hoverGlitchDesc') }}</li>
        <li>{{ t('logoExampleView.aliveEffects.toggleNote') }} <code>alive</code> {{ t('logoExampleView.aliveEffects.toggleNoteSuffix') }} <code>&lt;ProtocolMark&gt;</code></li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import ProtocolMark from '@/components/ProtocolMark.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>

<style scoped>
@import url('/fonts/fonts-extra.css'); /* §LEGALKIT: Vite inlines this public file at build time; the font URLs inside it are /static/fonts/, where the registry serves the dist (V0413) */

.lx-page {
  min-height: 100vh;
  background: #0A0A0A;
  color: #FAFAFA;
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
  padding: 3rem 2rem 6rem;
}
.lx-header { max-width: 1200px; margin: 0 auto 4rem; text-align: center; }
.lx-header h1 { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 1.5rem; letter-spacing: 0.18em; margin: 0 0 0.5rem; }
.lx-header p { color: #A0A0A0; font-size: 0.875rem; margin: 0; }

.lx-hero {
  max-width: 800px; margin: 0 auto 6rem;
  background: radial-gradient(circle at center, #1A0606 0%, #0A0A0A 70%);
  padding: 4rem 2rem; border: 1px solid #2A0A0A; text-align: center;
}
.lx-hero-mark { display: flex; justify-content: center; margin: 0 auto 2rem; }
.lx-wordmark {
  font-family: 'Orbitron', sans-serif;
  font-weight: 900;
  font-size: 3.5rem;
  letter-spacing: 0.06em;
  margin: 0 0 1rem;
  /* Chrome / brushed steel gradient */
  background: linear-gradient(180deg, #FFFFFF 0%, #E5E5E5 45%, #9A9A9A 50%, #C0C0C0 55%, #FAFAFA 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: 0 4px 24px rgba(0, 0, 0, 0.9);
  filter: drop-shadow(0 2px 0 rgba(0,0,0,0.5));
}
.lx-tag {
  font-family: 'Orbitron', sans-serif;
  font-weight: 500;
  font-size: 0.95rem;
  letter-spacing: 0.32em;
  color: #FF3838;
  margin: 0;
  text-shadow: 0 0 12px rgba(220, 38, 38, 0.4);
}

.lx-section { max-width: 1200px; margin: 0 auto 5rem; }
.lx-h3 {
  font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 0.875rem;
  letter-spacing: 0.22em; color: #FF3838; margin: 0 0 0.5rem;
  border-bottom: 1px solid #2A0A0A; padding-bottom: 0.75rem;
}
.lx-sub { color: #A0A0A0; font-size: 0.875rem; margin: 0 0 2rem; }

.lx-swatches { display: grid; grid-template-columns: repeat(7, 1fr); gap: 0.5rem; }
@media (max-width: 900px) { .lx-swatches { grid-template-columns: repeat(4, 1fr); } }
@media (max-width: 500px) { .lx-swatches { grid-template-columns: repeat(2, 1fr); } }
.lx-swatch {
  aspect-ratio: 1; padding: 1rem; display: flex; flex-direction: column; justify-content: space-between;
  color: #FAFAFA; font-family: 'IBM Plex Mono', monospace;
}
.lx-swatch span { font-size: 0.75rem; font-weight: 600; }
.lx-swatch small { font-size: 0.625rem; letter-spacing: 0.1em; }

.lx-lockups { display: flex; flex-direction: column; gap: 2rem; }
.lx-lockup { background: #0A0A0A; border: 1px solid #2A0A0A; padding: 2rem; }
.lx-lockup-inner { display: flex; align-items: center; gap: 1.5rem; }
.lx-stack { flex-direction: column; }
.lx-stack-text { text-align: center; }
.lx-lockup-name {
  font-family: 'Orbitron', sans-serif; font-weight: 900; font-size: 1.85rem; letter-spacing: 0.06em;
  background: linear-gradient(180deg, #FFFFFF 0%, #E5E5E5 45%, #9A9A9A 50%, #C0C0C0 55%, #FAFAFA 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.lx-lockup-tag { font-family: 'Orbitron', sans-serif; font-weight: 500; font-size: 0.72rem; letter-spacing: 0.32em; color: #FF3838; margin-top: 0.5rem; text-shadow: 0 0 8px rgba(220,38,38,0.4); }
.lx-lockup-label { margin-top: 1.5rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.18em; color: #848484; }
.lx-marks-row { display: flex; align-items: flex-end; gap: 2rem; flex-wrap: wrap; }

.lx-typo { display: flex; flex-direction: column; gap: 1.5rem; }
.lx-typo-row { background: #1A1A1A; border: 1px solid #2A0A0A; padding: 1.5rem; }
.lx-typo-sample { margin-bottom: 0.5rem; }
.lx-typo-meta { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.18em; color: #848484; }

.lx-apps { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.5rem; }
@media (max-width: 800px) { .lx-apps { grid-template-columns: 1fr; } }
/* a phone: the column may shrink below its content (a 1fr column grows to the mockups' widest line, past the screen),
   the names follow the width, a long URL wraps (the camera, 2026-10-13: "THE PROTOC" cut off, four mockups past the edge) */
@media (max-width: 600px) {
  .lx-wordmark { font-size: clamp(1.6rem, 8vw, 3.5rem); }
  .lx-apps { grid-template-columns: minmax(0, 1fr); }
  .lx-app-card { min-width: 0; padding: 1.25rem; gap: 1rem; }
  .lx-gh-mark { width: 64px; }
  .lx-gh-name { font-size: clamp(1.05rem, 5.5vw, 1.65rem); }
  .lx-login-name { font-size: clamp(1.15rem, 6vw, 1.85rem); }
  .lx-gh-meta { overflow-wrap: anywhere; }
}
.lx-app { display: flex; flex-direction: column; }
.lx-app-card { background: #0A0A0A; border: 1px solid #2A0A0A; padding: 2rem; aspect-ratio: 2 / 1; display: flex; align-items: center; gap: 2rem; }
.lx-app-label { margin-top: 1rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.18em; color: #848484; }
.lx-gh-card { background: #0D1117; border-color: #21262D; }
.lx-gh-mark { width: 100px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.lx-gh-name {
  font-family: 'Orbitron', sans-serif; font-weight: 900; font-size: 1.65rem; letter-spacing: 0.06em;
  background: linear-gradient(180deg, #FFFFFF 0%, #E5E5E5 45%, #9A9A9A 50%, #C0C0C0 55%, #FAFAFA 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.lx-typo-chrome {
  background: linear-gradient(180deg, #FFFFFF 0%, #E5E5E5 45%, #9A9A9A 50%, #C0C0C0 55%, #FAFAFA 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.lx-gh-tag { color: #C9D1D9; font-size: 1rem; margin: 0.5rem 0; }
.lx-gh-meta { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: #8B949E; }
.lx-term { padding: 0; flex-direction: column; align-items: stretch; aspect-ratio: 2 / 1.1; }
.lx-term-bar { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; background: #1A1A1A; border-bottom: 1px solid #2A0A0A; }
.lx-term-dot { width: 12px; height: 12px; border-radius: 50%; }
.lx-term-title { margin-left: 0.75rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: #A0A0A0; }
.lx-term-body { margin: 0; padding: 1.5rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; line-height: 1.6; color: #FF3838; white-space: pre; overflow: auto; }
.lx-fav { padding: 2rem; background: #1A1A1A; border-color: #2A0A0A; }
.lx-fav-tab { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.5rem 1rem; background: #2A2A2A; border-radius: 6px 6px 0 0; font-size: 0.8rem; color: #C0C0C0; }
.lx-login-mock { flex-direction: column; gap: 1rem; aspect-ratio: 2 / 1.4; padding: 2rem; background: radial-gradient(circle at center, #1A0606 0%, #0A0A0A 70%); }
.lx-login-name {
  font-family: 'Orbitron', sans-serif; font-weight: 900; font-size: 1.85rem; letter-spacing: 0.06em;
  background: linear-gradient(180deg, #FFFFFF 0%, #E5E5E5 45%, #9A9A9A 50%, #C0C0C0 55%, #FAFAFA 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  margin-top: 0.5rem;
}
.lx-login-sub { font-family: 'Orbitron', sans-serif; font-weight: 500; font-size: 0.72rem; letter-spacing: 0.32em; color: #FF3838; text-shadow: 0 0 8px rgba(220,38,38,0.4); }

.lx-live-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
@media (max-width: 700px) { .lx-live-grid { grid-template-columns: 1fr; } }
.lx-live-tile { background: #1A1A1A; border: 1px solid #2A0A0A; padding: 1.25rem; }
.lx-live-loc { font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 0.875rem; color: #FAFAFA; margin-bottom: 0.4rem; }
.lx-live-spec { font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; letter-spacing: 0.18em; color: #FF3838; }

.lx-taglines, .lx-notes { color: #C0C0C0; font-size: 0.95rem; line-height: 1.8; padding-left: 1.5rem; }
.lx-taglines li, .lx-notes li { margin-bottom: 0.6rem; }
.lx-taglines strong, .lx-notes strong { color: #FAFAFA; font-weight: 600; }
.lx-taglines em { color: #FF3838; font-style: normal; font-size: 0.8rem; margin-left: 0.5rem; }
.lx-notes code, .lx-sub code { background: #1A1A1A; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.85em; color: #FF3838; font-family: 'IBM Plex Mono', monospace; }
</style>
