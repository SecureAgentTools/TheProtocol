import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 3/6: the network side of your node.
//
// Reuses the public federation anchors (fed-hero on the h1, fed-tabs, fed-frames) and adds
// fed-ops (operations panel root) + compliance-hero. The operations tab is admin-gated in
// the UI (canFederation) — requireFlag matches. Route query `?tab=operations` selects the
// tab; the ops anchor still gets a fed-tabs fallback in case the panel is slow to mount.
export const opFederationTour: GuidedTour = {
  id: 'op-federation',
  title: 'Operator: Federation & Licenses',
  subtitle: 'Peers, licenses, and what revocation really means',
  icon: 'mdi:web',
  accent: '#a78bfa',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'admin_federation',
  steps: [
    {
      id: 'intro', title: 'Your node is a citizen', placement: 'center',
      body: 'Federation is what makes your registry part of a **network** instead of an ' +
        'island: peers discover each other, agents transact across nodes, and a signed ' +
        '**license** says who vouches for whom.\n\nThis tour covers the operator side: ' +
        'peers, licenses, compliance — and the teeth behind them.',
    },
    {
      id: 'hero', title: 'The federation map', anchor: 'fed-hero', placement: 'bottom', route: '/federation',
      body: 'The public view first: every peer your registry knows, grouped by tier — ' +
        'sovereign frames down to cloud operators. Reachability here is measured by ' +
        '**probing the peer\'s public URL**, not by trusting a stale row.',
    },
    {
      id: 'frames', title: 'Peers and their cards', anchor: 'fed-frames,fed-tabs', placement: 'top',
      body: 'Each card is a peer\'s signed **registry card**: name, role, currency, market ' +
        'capabilities. Click one for the drawer with its full identity.\n\nA peer being ' +
        '**visible** means "may connect" — it does not by itself mean "may move value".',
    },
    {
      id: 'ops-tab', title: 'The operations tab', anchor: 'fed-ops-tab,fed-tabs', placement: 'bottom',
      body: 'Beside the public tiers sits the admin-only **Operations** tab — visible only ' +
        'to accounts holding the federation area. Open it to see the governance side.',
      cta: { label: 'Open Operations', do: 'click-anchor' },
    },
    {
      id: 'ops', title: 'Licenses and levers', anchor: 'fed-ops,fed-tabs', placement: 'top',
      body: 'License counts by state (**active / suspended / revoked**), config-drift flags, ' +
        'per-peer compliance detail and the approve/deactivate levers for peer records — ' +
        'the whole governance surface in one panel.',
    },
    {
      id: 'licenses', title: 'Licenses are the teeth', placement: 'center',
      body: 'A federation license is what lets a peer operate under your frame\'s trust. ' +
        '**Suspending** it pauses the relationship; **revoking** it is economic quarantine — ' +
        'the peer\'s events stop being accepted and its issuing rights (it never had any, ' +
        'as a federated node) cannot be smuggled in.\n\nRevocation is reversible; nothing ' +
        'is deleted, only refused.',
    },
    {
      id: 'compliance', title: 'Compliance monitor', anchor: 'compliance-hero', placement: 'bottom', route: '/admin/compliance',
      body: 'The observation layer: every peer polled on a cycle, drift between what a peer ' +
        '**claims** and what it **serves** flagged here. Today the fleet runs this in ' +
        'observation mode — it reports, humans decide.',
    },
    {
      id: 'outro', title: 'Network, governed', placement: 'center',
      body: 'Peers you can see, licenses you can pull, drift you can catch early.\n\n' +
        'Next: **Operator: Treasury & Money** — the funding rails and where the fees go.',
    },
  ],
}
