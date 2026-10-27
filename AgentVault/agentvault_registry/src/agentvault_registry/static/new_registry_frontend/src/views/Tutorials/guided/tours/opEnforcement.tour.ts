import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 5/6: the levers you hope to never pull.
//
// Agents admin (suspension levers) → IRONHAND (mTLS revocation) → audit trail →
// READONLY_MODE break-glass (centered; it is an env flip, not a UI element).
export const opEnforcementTour: GuidedTour = {
  id: 'op-enforcement',
  title: 'Operator: Enforcement & Safety',
  subtitle: 'Suspension, revocation, and the break-glass switch',
  icon: 'mdi:gavel',
  accent: '#f87171',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'admin_enforcement',
  steps: [
    {
      id: 'intro', title: 'Power, with receipts', placement: 'center',
      body: 'Enforcement on this platform is **deny-shaped**: every lever refuses actions, ' +
        'freezes access or revokes identity — none of them move money. That is deliberate: ' +
        'a compromised admin can lock things, but cannot drain them.\n\nEverything you do ' +
        'here lands in the audit trail.',
    },
    {
      id: 'agents', title: 'Suspending an agent', anchor: 'admin-agents-hero', placement: 'bottom', route: '/admin/agents',
      body: 'The agent roster carries the per-agent levers. **Coordinated suspension** is one ' +
        'action with four teeth: registry status flip, mTLS certificate revocation, TEG ' +
        'account suspension and a cross-registry receive-block — so a suspended agent ' +
        'cannot sidestep you by transacting elsewhere. Reinstatement reverses all four.',
    },
    {
      id: 'ironhand', title: 'IRONHAND: identity revocation', anchor: 'ironhand-hero', placement: 'bottom', route: '/admin/ironhand',
      body: 'Agents authenticate peer-to-peer with short-lived **mTLS certificates**. This ' +
        'theatre shows every issued identity and lets you revoke one: propagation is ' +
        'push-first (sub-second via the event stream), polling second, and certificate ' +
        'expiry is the backstop. Revoked means **cryptographically** out, not just flagged.',
    },
    {
      id: 'permissions', title: 'The quieter enforcement layer', placement: 'center',
      body: 'Below the levers sits agent RBAC (**IRONKEY**): every agent action is checked ' +
        'against its roles and spend limits **before** money moves. Most bad days end here — ' +
        'a denial in the log — without any human pulling anything.\n\nDenials name the ' +
        'missing permission, so diagnosis is one audit-log search away.',
    },
    {
      id: 'audit', title: 'The trail', anchor: 'audit-hero', placement: 'bottom', route: '/admin/audit-logs',
      body: 'Every enforcement decision — who suspended what, which certificate was revoked, ' +
        'which permission denied — is a row here. When you act under pressure, this is what ' +
        'lets you (and anyone reviewing you) reconstruct the story afterwards.',
    },
    {
      id: 'breakglass', title: 'Break-glass: freeze everything', placement: 'center',
      body: 'The last resort is not in any UI, by design: set `READONLY_MODE=true` in the ' +
        'env file and recreate the registry container. Every write answers **503**, all ' +
        'background write loops freeze, the MCP surface is refused — while reads, login and ' +
        'the supply auditors keep running.\n\nIt is env-only so that **no stolen admin ' +
        'token can switch it back off**. Undoing it takes another recreate, deliberately.',
    },
    {
      id: 'outro', title: 'Hope to never need it', placement: 'center',
      body: 'Suspension with four teeth, cryptographic revocation, a permission layer that ' +
        'catches most trouble silently, and a freeze switch no token can flip.\n\nLast in ' +
        'the series: **Operator: Connect Your Assistant**.',
    },
  ],
}
