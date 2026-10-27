import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 2/6: the daily-driving admin views.
//
// Command Center overview → developers → agents → audit trail → reactors. Each stop is a
// hero anchor (always renders) so the tour cannot strand on data-dependent elements.
export const opWatchtowerTour: GuidedTour = {
  id: 'op-watchtower',
  title: 'Operator: Watchtower Basics',
  subtitle: 'The five views you will open every day',
  icon: 'mdi:server-network',
  accent: '#38bdf8',
  estMinutes: 5,
  requireAdmin: true,
  steps: [
    {
      id: 'intro', title: 'Your control room', placement: 'center',
      body: 'The **Admin Watchtower** is a family of views under one roof: platform totals, ' +
        'people, agents, the audit trail, and the machinery that runs in the background.\n\n' +
        'This tour visits the five you will actually open every day.',
    },
    {
      id: 'cc', title: 'Command Center', anchor: 'cc-overview', placement: 'bottom', route: '/command-center',
      body: 'The overview: developers, agents, activity and health at a glance, with jump-off ' +
        'points into every deeper view. When something is wrong on your node, this page ' +
        'usually says so first.',
    },
    {
      id: 'devs', title: 'Developers', anchor: 'admin-devs-hero', placement: 'bottom', route: '/admin/developers',
      body: 'Every human (and service account) on your registry. Verify state, admin areas, ' +
        'quotas, suspension — and the **granular admin flags** each account holds. This is ' +
        'where you audit **who can do what** after handing out invitations.',
    },
    {
      id: 'agents', title: 'Agents', anchor: 'admin-agents-hero', placement: 'bottom', route: '/admin/agents',
      body: 'Every agent, with status, owner, balances and enforcement levers. Deletion here ' +
        'is a **soft delete** — the agent goes to **revoked** and its balance stays put, so ' +
        'money never vanishes with an identity.',
    },
    {
      id: 'audit', title: 'Audit logs', anchor: 'audit-hero', placement: 'bottom', route: '/admin/audit-logs',
      body: 'The security audit trail: admin actions, auth events, enforcement decisions — ' +
        'and, if you enable MCP audit logging, every tool call an AI assistant makes. When ' +
        'you need to answer **"who did this?"**, start here.',
    },
    {
      id: 'reactors', title: 'Reactors & workers', anchor: 'reactors-hero', placement: 'bottom', route: '/admin/reactors',
      body: 'The background machinery: event **reactors** and leader-elected **workers** — ' +
        'health checks, sync loops, payout distributors, the supply auditor. A stuck worker ' +
        'shows up here long before users notice anything.',
    },
    {
      id: 'outro', title: 'That is the daily loop', placement: 'center',
      body: 'Overview → people → agents → trail → machinery. Ten minutes a day here is most ' +
        'of running a healthy registry.\n\nNext: **Operator: Federation & Licenses** for the ' +
        'network side of your node.',
    },
  ],
}
