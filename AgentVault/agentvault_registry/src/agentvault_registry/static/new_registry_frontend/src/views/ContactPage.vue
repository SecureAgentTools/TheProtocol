<template>
<div class="gs">
  <!-- Ambient -->
  <div class="gs-ambient">
    <div class="gs-grid"></div>
    <div class="gs-scan"></div>
    <div class="gs-glow gs-glow-1"></div>
    <div class="gs-glow gs-glow-2"></div>
  </div>

  <!-- ═══ HERO ═══ -->
  <section class="gs-hero">
    <div class="gs-hero-inner">
      <div class="gs-chip"><span class="gs-chip-dot"></span>{{ t('contactView.chip', 'CONTACT') }}</div>
      <h1 class="gs-h1">{{ t('contactView.h1a', 'Talk to') }} <span class="gs-accent">{{ t('contactView.h1Accent', 'the operator') }}</span></h1>
      <p class="gs-lead">{{ t('contactView.lead', 'TheProtocol is run by its founder. Mail lands in front of the person who wrote the code, which is efficient, and answered by the same person, which is sometimes not. Expect honest, asynchronous replies.') }}</p>
    </div>
  </section>

  <!-- ═══ CHANNELS ═══ -->
  <section class="gs-sec">
    <div class="gs-layers">
      <div class="gs-layer">
        <div class="gs-layer-num">@</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('contactView.email.title', 'Email') }}</h3>
          <p class="gs-layer-text">
            {{ t('contactView.email.text', 'One address for everything: partnerships, press, operators, questions, complaints.') }}
            <a class="gs-mail" href="mailto:commander@theprotocol.cloud">commander@theprotocol.cloud</a>
          </p>
        </div>
      </div>
      <!-- his word 2026-10-03: no Discord on the contact page (as on the landing) -->
      <div class="gs-layer">
        <div class="gs-layer-num">!</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('contactView.security.title', 'Security disclosures') }}</h3>
          <p class="gs-layer-text">{{ t('contactView.security.text', 'Found a vulnerability? Mail the address above with [SECURITY] in the subject line. Reports are read first, acknowledged honestly, and never punished.') }}</p>
        </div>
      </div>
      <div class="gs-layer">
        <div class="gs-layer-num">?</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('contactView.support.title', 'Account support') }}</h3>
          <p class="gs-layer-text">{{ t('contactView.support.text', 'Signed-in users can open a support ticket from the dashboard; tickets are tracked on the platform itself, so nothing gets lost in an inbox.') }}</p>
        </div>
      </div>
    </div>

    <div class="gs-card" style="margin-top: 24px;">
      <h3 class="gs-card-title">{{ t('contactView.legal.title', 'Legal contact') }}</h3>
      <p class="gs-card-text">
        {{ t('contactView.legal.text', 'The legally required provider identification, postal address and supervisory details are in the imprint.') }}
        <router-link to="/legal/imprint" class="gs-inline-link">{{ t('contactView.legal.cta', 'Open the imprint →') }}</router-link>
      </p>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="gs-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/" class="gs-btn gs-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; {{ t('contactView.back', 'Back to Home') }}
    </router-link>
  </section>

  <footer class="gs-footer">
    <div class="gs-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="gs-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/pricing">Pricing</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/legal/imprint">Imprint</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
</script>

<style scoped>
.gs {
  --bg: #060a12;
  --border: rgba(var(--nc-primary-rgb),0.08);
  --cyan: var(--nc-primary);
  --green: #00e676;
  --text: #b0bec5;
  --text-bright: #e0e6eb;
  --muted: #78909c;
  --mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;
  background: var(--bg); color: var(--text);
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}

.gs-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.gs-grid { position: absolute; inset: 0; background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px), linear-gradient(90deg,rgba(var(--nc-primary-rgb),0.03) 1px,transparent 1px); background-size: 60px 60px; }
.gs-scan { position: absolute; top: 0; left: 0; width: 100%; height: 180px; background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.06), rgba(var(--nc-primary-rgb),0.02) 40%, transparent); animation: gsScan 12s linear infinite; }
@keyframes gsScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 1200px)); } }
.gs-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.gs-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.gs-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

.gs-hero { position: relative; min-height: 38vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.gs-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.gs-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.gs-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.gs-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.gs-accent { color: var(--cyan); }
.gs-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 620px; }

.gs-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }

.gs-layers { display: flex; flex-direction: column; gap: 16px; }
.gs-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.gs-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.gs-layer-body { flex: 1; }
.gs-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.gs-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }
.gs-mail { display: inline-block; font-family: var(--mono); font-size: 13px; color: var(--cyan); text-decoration: none; margin-left: 6px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.3); }
.gs-mail:hover { opacity: 0.75; }

.gs-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.gs-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.gs-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }
.gs-inline-link { font-family: var(--mono); font-size: 12px; color: var(--cyan); text-decoration: none; letter-spacing: 0.03em; transition: opacity 0.2s; margin-left: 6px; }
.gs-inline-link:hover { opacity: 0.7; }

.gs-btn { display: inline-flex; align-items: center; gap: 8px; padding: 10px 22px; border-radius: 4px; font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; text-decoration: none; cursor: pointer; transition: all 0.2s; font-family: var(--mono); border: none; }
.gs-btn-ghost { background: transparent; color: var(--text); border: 1px solid rgba(255,255,255,0.12); }
.gs-btn-ghost:hover { border-color: rgba(var(--nc-primary-rgb),0.3); color: var(--cyan); }

.gs-footer { position: relative; z-index: 1; border-top: 1px solid rgba(255,255,255,0.04); padding: 20px 2rem; font-size: 11px; color: var(--muted); }
.gs-footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; }
/* the links wrap whole on a phone, where the row ran past the screen ("Operator" cut off, "Units & Fees" on three
   lines; the camera, 2026-10-13) */
.gs-footer-links { display: flex; flex-wrap: wrap; gap: 8px 20px; }
.gs-footer-links a { color: var(--muted); text-decoration: none; font-size: 11px; white-space: nowrap; }
.gs-footer-links a:hover { color: var(--text-bright); }
</style>
