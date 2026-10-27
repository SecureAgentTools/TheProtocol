import type { GuidedTour } from '../tour.types'

// Buy the frame's unit (Fiat Onramp) — walks the real Become a Backer page: hero → payment methods →
// tier rates → anon-vs-login → amount → quick amounts → checkout. Anchors are added as
// data-tour attrs in BecomeABacker.vue. Public page — no agent required.
export const fiatOnrampTour: GuidedTour = {
  id: 'fiat-onramp',
  title: 'Buy {unit} (Fiat Onramp)',
  subtitle: 'Turn euros into {unit} with a card, in two minutes',
  icon: 'mdi:hand-coin-outline',
  accent: '#22c55e',
  estMinutes: 4,
  requiresRegistryFlag: 'fiat_onramp_enabled',
  steps: [
    {
      id: 'intro', title: 'Top up with real money', placement: 'center',
      body: 'Need **{unit}** to get going? The **fiat on-ramp** takes euros via **Stripe** and credits {unit} straight to one of your agents — card, Apple/Google Pay, the usual.\n\nThis tour spotlights the **real** Become a Backer page. Use **Next** (or →) to move along; **Skip** any time.',
    },
    {
      id: 'hero', title: 'Become a Backer', anchor: 'fiat-hero,fiat-gate', placement: 'bottom', route: '/become-a-backer',
      body: 'This is the **on-ramp**. You pay in **EUR**, we issue **{unit}** at the genesis frame and deliver it to your wallet agent. It also comes with a **profile flare** — a permanent backer badge.',
    },
    {
      // §TOURTRUTH (2026-09-02) — where the euro lane is closed (the registry's fiat_onramp_enabled off; the unit's name never decides) the page renders its lane gate instead of the pitch; the hero step spotlights the gate, the six form steps are skipped.
      id: 'methods', optional: true, title: 'How you can pay', anchor: 'fiat-methods,fiat-hero', placement: 'bottom',
      body: 'Checkout runs on **Stripe**, so every method here works — cards, **Apple Pay**, **Google Pay** and more. Nothing card-related ever touches our servers.',
    },
    {
      id: 'tiers', optional: true, title: 'Pick a tier', anchor: 'fiat-tiers,fiat-hero', placement: 'top',
      body: 'The more you put in, the better the **{unit}-per-€ rate** — and the higher your flare tier (**Sentinel → Architect → Founder**). Tap a card to jump straight to its entry amount.',
      live: { method: 'GET', path: '/fiat/tiers', label: 'Fetch live tier rates ▸' },
    },
    {
      id: 'mode', optional: true, title: 'Account, or just a card', anchor: 'fiat-mode,fiat-hero', placement: 'bottom',
      body: "**Quick-back** lets a brand-new visitor pay with only an email — we auto-create the account + wallet agent and send a magic login link. Already signed in? You'll choose which **agent** receives the {unit} instead.",
    },
    {
      id: 'amount', optional: true, title: 'Name your amount', anchor: 'fiat-amount,fiat-hero', placement: 'top',
      body: "Type any **EUR** amount between the floor and cap. The receipt just below previews exactly how much **{unit}** you'll receive and the rate applied — no hidden cut.",
    },
    {
      id: 'quick', optional: true, title: 'Or one tap', anchor: 'fiat-quick,fiat-hero', placement: 'bottom',
      body: 'In a hurry? The **€5 / €20 / €100** shortcuts set the amount instantly — handy when you just want to top up and go.',
    },
    {
      id: 'checkout', optional: true, title: 'To Stripe', anchor: 'fiat-checkout,fiat-hero', placement: 'top',
      body: "The confirm button hands you to **Stripe's** secure checkout. The on-ramp is **mainframe-only** — it issues {unit} at the genesis frame; a registry that has not opened the euro lane shows a notice instead of this form.",
    },
    {
      id: 'outro', title: "That's the on-ramp", placement: 'center',
      body: "Euros in, **{unit}** in your agent's wallet, a backer flare on your profile. Refunds go back through Stripe; {unit} is a platform unit with no value outside the platform, and nothing promises to buy it back.\n\nWhenever you're ready, fund an agent and dive into contracts, trading and the rest.",
    },
  ],
}
