<template>
  <!--
    PaymentLogos — PB-1 trust strip (2026-05-09).

    Inline SVG brand-marks for Stripe-Checkout payment methods. Rendered
    monochrome for visual cohesion with the active brand theme; on hover
    each logo animates up + shifts to its native brand color.

    The SVGs are inserted via v-html (string concat in script setup) so
    Vue's compiler doesn't try to recursively render text nodes inside
    SVG elements (an earlier inline-template version triggered a Vue
    "Maximum call stack size exceeded" recursion via the text-node path).

    Stripe TOS permits these monochrome representations on Checkout-integrated
    merchants. All paths are clean re-traces — no embedded copyrighted assets.
  -->
  <div :class="['plg-strip', `plg-strip-${props.size}`, { 'plg-strip-tight': props.tight }]">
    <span v-if="props.showLabel" class="plg-label">{{ props.label }}</span>
    <div class="plg-logos">
      <span
        v-for="logo in LOGOS"
        :key="logo.key"
        :class="['plg-logo', `plg-logo-${logo.key}`]"
        role="img"
        :title="logo.title"
        :aria-label="logo.title"
        v-html="logo.svg"
      />
    </div>
    <div v-if="props.stripeBadge" class="plg-stripe-badge">
      <span class="plg-stripe-lock" aria-hidden="true"><Icon name="mdi:lock" /></span>
      <span>Powered by</span>
      <span class="plg-stripe-name">Stripe</span>
      <span class="plg-stripe-sep">·</span>
      <span>PCI-DSS · 3DS2</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
const props = withDefaults(defineProps<{
  size?: 'sm' | 'md' | 'lg'
  stripeBadge?: boolean
  showLabel?: boolean
  label?: string
  tight?: boolean
}>(), {
  size: 'md',
  stripeBadge: true,
  showLabel: true,
  label: 'WE ACCEPT',
  tight: false,
})

// Build SVG strings outside the template — Vue's render compiler doesn't
// recurse into v-html content. Color is currentColor for theme handoff.
const LOGOS: Array<{ key: string; title: string; svg: string }> = [
  {
    key: 'visa',
    title: 'Visa',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="3" fill="currentColor" opacity="0.16" stroke="currentColor" stroke-opacity="0.30"/>
  <text x="30" y="16" text-anchor="middle" font-family="Helvetica, Arial, system-ui, sans-serif" font-size="12" font-weight="900" font-style="italic" letter-spacing="1.4" fill="currentColor">VISA</text>
</svg>`,
  },
  {
    key: 'mc',
    title: 'Mastercard',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="24" cy="11" r="8.5" fill="currentColor" opacity="0.85"/>
  <circle cx="36" cy="11" r="8.5" fill="currentColor" opacity="0.50"/>
</svg>`,
  },
  {
    key: 'amex',
    title: 'American Express',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="3" fill="currentColor" opacity="0.16" stroke="currentColor" stroke-opacity="0.30"/>
  <text x="30" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9" font-weight="800" letter-spacing="0.6" fill="currentColor">AMEX</text>
</svg>`,
  },
  {
    key: 'klarna',
    title: 'Klarna',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="11" fill="currentColor" opacity="0.16"/>
  <text x="30" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9.5" font-weight="700" letter-spacing="0.2" fill="currentColor">Klarna.</text>
</svg>`,
  },
  {
    key: 'sepa',
    title: 'SEPA Direct Debit',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="3" fill="currentColor" opacity="0.12" stroke="currentColor" stroke-opacity="0.40"/>
  <text x="30" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9.5" font-weight="700" letter-spacing="0.7" fill="currentColor">SEPA</text>
</svg>`,
  },
  {
    key: 'link',
    title: 'Stripe Link',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="11" fill="currentColor" opacity="0.16"/>
  <text x="30" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9.5" font-weight="600" letter-spacing="0.4" fill="currentColor">Link</text>
</svg>`,
  },
  {
    key: 'apay',
    title: 'Apple Pay',
    svg: `
<svg viewBox="0 0 60 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="59" height="21" rx="3" fill="currentColor" opacity="0.12"/>
  <text x="30" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9.5" font-weight="600" letter-spacing="0.3" fill="currentColor">Pay</text>
</svg>`,
  },
  {
    key: 'gpay',
    title: 'Google Pay',
    svg: `
<svg viewBox="0 0 64 22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <rect x="0.5" y="0.5" width="63" height="21" rx="3" fill="currentColor" opacity="0.12"/>
  <text x="32" y="15" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif" font-size="9.5" font-weight="600" letter-spacing="0.3" fill="currentColor">G Pay</text>
</svg>`,
  },
]
</script>

<style scoped>
.plg-strip {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  width: 100%;
  margin: 0 auto;
  padding: 14px 18px;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.30) 0%, rgba(0, 0, 0, 0.18) 100%);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 12px;
  position: relative;
  overflow: hidden;
}
.plg-strip::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 1px;
  background: linear-gradient(90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb, 0, 210, 210), 0.50) 50%,
    transparent 100%);
}
.plg-strip-tight { padding: 8px 16px; gap: 6px; }
.plg-strip-lg    { padding: 18px 22px; gap: 14px; }
.plg-strip-sm    { padding: 10px 14px; gap: 6px; }

.plg-label {
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  opacity: 0.45;
}

.plg-logos {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14px;
}

.plg-logo {
  display: inline-flex;
  align-items: center;
  height: 22px;
  color: rgba(255, 255, 255, 0.62);
  transition: color 250ms ease, transform 250ms ease, opacity 250ms ease;
  cursor: default;
  flex-shrink: 0;
}
.plg-logo :deep(svg) {
  height: 22px;
  width: auto;
  display: block;
}
.plg-logo:hover {
  transform: translateY(-1px);
  opacity: 1;
}

.plg-logo-visa:hover   { color: rgb(140, 190, 230); }
.plg-logo-mc:hover     { color: rgb(255, 95, 0); }
.plg-logo-amex:hover   { color: rgb(86, 175, 230); }
.plg-logo-klarna:hover { color: rgb(255, 178, 199); }
.plg-logo-sepa:hover   { color: rgb(173, 216, 230); }
.plg-logo-link:hover   { color: rgb(64, 218, 187); }
.plg-logo-apay:hover   { color: rgb(245, 245, 247); }
.plg-logo-gpay:hover   { color: rgb(255, 255, 255); }

.plg-stripe-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.06em;
  opacity: 0.55;
}
.plg-stripe-lock { font-size: 11px; opacity: 0.85; }
.plg-stripe-name {
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.75);
}
.plg-stripe-sep { opacity: 0.40; padding: 0 2px; }

@media (max-width: 640px) {
  .plg-logos { gap: 8px; }
  .plg-logo { height: 18px; }
  .plg-logo :deep(svg) { height: 18px; }
  .plg-stripe-badge { font-size: 9px; flex-wrap: wrap; justify-content: center; }
}
</style>
