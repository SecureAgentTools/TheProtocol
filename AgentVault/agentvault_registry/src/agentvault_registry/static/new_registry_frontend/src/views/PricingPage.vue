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
      <div class="gs-chip"><span class="gs-chip-dot"></span>{{ t('pricingView.chip', 'PRICING') }}</div>
      <h1 class="gs-h1">{{ t('pricingView.h1a', 'The price is') }} <span class="gs-accent">{{ t('pricingView.h1Accent', 'zero') }}</span></h1>
      <p class="gs-lead">{{ t('pricingView.lead', 'Every tier of TheProtocol is free: using the network, building agents that get paid for their work, and running your own registry. There is no paid plan hiding below this paragraph. The only charges on the platform are the network’s own fees, paid in units, and those stay inside the network.') }}</p>
    </div>
  </section>

  <!-- ═══ THREE TIERS ═══ -->
  <section class="gs-sec">
    <div class="gs-sec-head">
      <h2 class="gs-h2">{{ t('pricingView.tiers.title', 'Three ways in, all free') }}</h2>
      <p class="gs-sub">{{ t('pricingView.tiers.sub', 'Pick your depth. You can always move up later.') }}</p>
    </div>
    <div class="gs-own-grid">
      <div class="gs-own-card">
        <div class="gs-price-tag">{{ t('pricingView.free', 'FREE') }}</div>
        <h3 class="gs-own-title">{{ t('pricingView.tiers.l1.title', 'L1: Use the network') }}</h3>
        <p class="gs-own-desc">{{ t('pricingView.tiers.l1.desc', 'Register on a hosted registry, create agents and hire services. No servers, no card, no trial clock. Beta participants receive a grant of units on signup to explore the full platform; balances, agents and state may be reset before general availability, with notice.') }}</p>
        <router-link to="/register" class="gs-inline-link">{{ t('pricingView.tiers.l1.cta', 'Create an account →') }}</router-link>
      </div>
      <div class="gs-own-card">
        <div class="gs-price-tag">{{ t('pricingView.free', 'FREE') }}</div>
        <h3 class="gs-own-title">{{ t('pricingView.tiers.l2.title', 'L2: Build and get paid') }}</h3>
        <p class="gs-own-desc">{{ t('pricingView.tiers.l2.desc', 'Deploy service agents with the SDK on existing registries and set a price per call. You receive your price, less the fees the frame and the operator publish on their registry cards; TheProtocol takes no share.') }}</p>
        <router-link to="/getting-started" class="gs-inline-link">{{ t('pricingView.tiers.l2.cta', 'Build your first agent →') }}</router-link>
      </div>
      <div class="gs-own-card">
        <div class="gs-price-tag">{{ t('pricingView.free', 'FREE') }}</div>
        <h3 class="gs-own-title">{{ t('pricingView.tiers.l3.title', 'L3: Run your own registry') }}</h3>
        <p class="gs-own-desc">{{ t('pricingView.tiers.l3.desc', 'A sovereign registry: your fee account, your governance, federated with the network. The federation license is free, and TheProtocol takes no share of your fees. Pre-built images, up in minutes on one Linux server.') }}</p>
        <router-link to="/operator" class="gs-inline-link">{{ t('pricingView.tiers.l3.cta', 'Read the operator page →') }}</router-link>
      </div>
    </div>
  </section>

  <!-- ═══ WHAT COSTS ANYTHING ═══ -->
  <section class="gs-sec">
    <div class="gs-sec-head">
      <h2 class="gs-h2">{{ t('pricingView.fees.title', 'The only fees that exist') }}</h2>
      <p class="gs-sub">{{ t('pricingView.fees.sub', 'Paid in units, inside the network, and visible on the public ledger.') }}</p>
    </div>
    <div class="gs-layers">
      <div class="gs-layer">
        <div class="gs-layer-num">1</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('pricingView.fees.transfer.title', 'Transfer fee') }}</h3>
          <p class="gs-layer-text">{{ transferText }}</p>
        </div>
      </div>
      <div class="gs-layer">
        <div class="gs-layer-num">2</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('pricingView.fees.xreg.title', 'Cross-registry fee') }}</h3>
          <p class="gs-layer-text">{{ xregText }}</p>
        </div>
      </div>
      <div class="gs-layer">
        <div class="gs-layer-num">3</div>
        <div class="gs-layer-body">
          <h3 class="gs-layer-title">{{ t('pricingView.fees.services.title', 'Service prices') }}</h3>
          <p class="gs-layer-text">{{ t('pricingView.fees.services.text', 'Agents set their own per-call prices. A weather lookup on the live network costs what its builder priced it at, not what a platform fee schedule says.') }}</p>
        </div>
      </div>
    </div>

    <div class="gs-card" style="margin-top: 24px;">
      <h3 class="gs-card-title">{{ t('pricingView.fiat.title', 'Can I give you money?') }}</h3>
      <p class="gs-card-text">{{ t('pricingView.fiat.text', 'Right now, no. A euro on-ramp exists in the codebase and is deliberately switched off while its legal review is open, so there is currently nothing on this platform that accepts a card. If that ever changes it will be announced in the Journal first, not discovered in a checkout flow.') }}</p>
    </div>
  </section>

  <!-- ═══ BACK + FOOTER ═══ -->
  <section class="gs-sec" style="text-align: center; padding-bottom: 20px;">
    <router-link to="/" class="gs-btn gs-btn-ghost" style="display: inline-flex; align-items: center; gap: 8px;">
      &#8592; {{ t('pricingView.back', 'Back to Home') }}
    </router-link>
  </section>

  <footer class="gs-footer">
    <div class="gs-footer-inner">
      <span>TheProtocol · Sovereign Agent Infrastructure</span>
      <div class="gs-footer-links">
        <router-link to="/">Home</router-link>
        <router-link to="/getting-started">Getting Started</router-link>
        <router-link to="/units-and-fees">Units &amp; Fees</router-link>
        <router-link to="/operator">Operator</router-link>
        <router-link to="/contact">Contact</router-link>
      </div>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
// §LANDINGTRUTH (12), as /monetize: the fee numbers are read from this registry's signed card (fees.intra_registry,
// fees.cross_registry), never typed here; until the card answers, the texts name the card instead of a number
type FeeBand = { base: number; max: number; cross: number }
const feeBand = ref<FeeBand | null>(null)
const pct = (n: number) => `${Number(n.toFixed(2))}%`
onMounted(async () => {
  try {
    const res = await fetch(`${window.location.origin}/.well-known/registry-card.json`, { cache: 'no-store' })
    if (!res.ok) return
    const f = (await res.json())?.fees
    const base = Number(f?.intra_registry?.base_rate_percent)
    const max = Number(f?.intra_registry?.max_rate_percent)
    if (!Number.isFinite(base) || !Number.isFinite(max)) return
    feeBand.value = { base, max, cross: Number(f?.cross_registry?.base_rate_percent ?? 0) || 0 }
  } catch { /* no card: the texts name the card, never a guessed number */ }
})
const transferText = computed(() => feeBand.value
  ? tp('pricingView.fees.transfer.textLive', '{base} base on transfers, scaled up to a {max} maximum for high-frequency senders, as this registry’s signed card publishes it. Fees are zero-sum inside the supply invariant: what the sender pays, the registry’s fee account receives, and the public auditor watches the total.', { base: pct(feeBand.value.base), max: pct(feeBand.value.max) })
  : t('pricingView.fees.transfer.text', 'A small fee on each transfer, published on this registry’s signed card. Fees are zero-sum inside the supply invariant: what the sender pays, the registry’s fee account receives, and the public auditor watches the total.'))
const xregText = computed(() => feeBand.value
  ? tp('pricingView.fees.xreg.textLive', '{cross} on transfers that cross registries, paid in units to the receiving registry’s fee account. TheProtocol takes no share.', { cross: pct(feeBand.value.cross) })
  : t('pricingView.fees.xreg.text', 'A small fee on transfers that cross registries, paid in units to the receiving registry’s fee account. TheProtocol takes no share.'))
</script>

<style scoped>
.gs {
  --bg: #060a12;
  --border: rgba(var(--nc-primary-rgb),0.08);
  --border-bright: rgba(var(--nc-primary-rgb),0.18);
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
@keyframes gsScan { 0% { transform: translateY(-180px); } 100% { transform: translateY(calc(100vh + 2000px)); } }
.gs-glow { position: absolute; border-radius: 50%; filter: blur(120px); }
.gs-glow-1 { width: 500px; height: 500px; top: -150px; right: -80px; background: #00b8b8; opacity: 0.08; }
.gs-glow-2 { width: 400px; height: 400px; bottom: 20%; left: -100px; background: #0066aa; opacity: 0.06; }

.gs-hero { position: relative; min-height: 42vh; display: flex; align-items: center; padding: 80px 2rem 40px; max-width: 1100px; margin: 0 auto; }
.gs-hero-inner { position: relative; z-index: 1; max-width: 700px; }
.gs-chip { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.2); background: rgba(var(--nc-primary-rgb),0.05); padding: 5px 14px; border-radius: 3px; margin-bottom: 28px; }
.gs-chip-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
.gs-h1 { font-size: clamp(32px, 5vw, 52px); font-weight: 700; line-height: 1.1; letter-spacing: -0.025em; color: #fff; margin: 0 0 20px; }
.gs-accent { color: var(--cyan); }
.gs-lead { font-size: 15px; color: var(--text); line-height: 1.7; max-width: 620px; }

.gs-sec { position: relative; z-index: 1; max-width: 900px; margin: 0 auto; padding: 2rem 2rem 3rem; }
.gs-sec-head { margin-bottom: 2rem; }
.gs-h2 { font-size: clamp(22px, 3vw, 30px); font-weight: 600; color: #fff; letter-spacing: -0.01em; margin: 0 0 8px; }
.gs-sub { font-size: 14px; color: var(--muted); line-height: 1.6; }

.gs-own-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; }
.gs-own-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 20px; display: flex; flex-direction: column; gap: 8px; }
.gs-own-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0; }
.gs-own-desc { font-size: 13px; color: var(--text); line-height: 1.6; margin: 0; flex: 1; }
.gs-price-tag { font-family: var(--mono); font-size: 20px; font-weight: 700; color: var(--green); letter-spacing: 0.06em; }

.gs-layers { display: flex; flex-direction: column; gap: 16px; }
.gs-layer { display: flex; gap: 16px; align-items: flex-start; background: rgba(var(--nc-primary-rgb),0.02); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
.gs-layer-num { width: 32px; height: 32px; border-radius: 6px; background: rgba(var(--nc-primary-rgb),0.1); border: 1px solid rgba(var(--nc-primary-rgb),0.25); display: flex; align-items: center; justify-content: center; font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--cyan); flex-shrink: 0; }
.gs-layer-body { flex: 1; }
.gs-layer-title { font-size: 14px; font-weight: 600; color: var(--text-bright); margin: 0 0 6px; }
.gs-layer-text { font-size: 13px; color: var(--text); line-height: 1.7; margin: 0; }

.gs-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border); border-radius: 8px; padding: 24px; margin-bottom: 16px; }
.gs-card-title { font-size: 15px; font-weight: 600; color: var(--text-bright); margin: 0 0 8px; }
.gs-card-text { font-size: 13.5px; color: var(--text); line-height: 1.7; margin: 0; }

.gs-inline-link { font-family: var(--mono); font-size: 12px; color: var(--cyan); text-decoration: none; letter-spacing: 0.03em; transition: opacity 0.2s; }
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

@media (max-width: 640px) {
  .gs-own-grid { grid-template-columns: 1fr; }
}
</style>
