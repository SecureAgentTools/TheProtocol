// V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the console's nav table, his task groups of 2026-11-13
// (sessionlogs2026/BACKLOG_2026-11-08_NIGHT.md: Work, Agents, Organizations, Economy, Governance, Network views,
// Developer; Administration in sub-groups). One table for the sidebar, its search and the palette's pins.
//
// ONE RULE: an entry keeps no admin flag of its own. Who sees it is read from the route it opens (services/nav/navAccess:
// the router's requiresRole / requiresAdminFlag / requiresAuth / allowAnonymous), the meta the guard enforces. Only a
// tab inside a member page (its route is not admin-gated) names the flag its tab needs (adminFlag).
// The entries are the sidebar's of V0661 (DashboardSidebar.vue), moved here as they were, regrouped, the four all-caps
// labels in title case (his "no all-caps items"), and "Onboarding" named as the console shows it (Quick onboarding).
import type { AdminAction } from '@/composables/usePermissions'

export interface NavItem {
  name: string
  /** the label's key; the label falls back to name */
  i18nKey?: string
  path: string
  icon: string
  color: string
  requiresAgent?: boolean
  /** a tab inside a member page that needs an admin flag (its route is not admin-gated itself) */
  adminFlag?: AdminAction
  authHint?: string
  /** a live counter beside the label (OurChat's unread) */
  badgeKey?: 'chat'
  mainframeOnly?: boolean
  /** shown only to a person who holds a backer flare */
  requiresFlare?: boolean
  /** locked where the euro lane is off */
  requiresFiat?: boolean
  /** shown only where this registry serves the feature */
  requiresRegistryFlag?: 'cockpit_desk_enabled' | 'frame_kit_enabled' | 'staking_enabled' | 'fiat_onramp_enabled' | 'workflow_templates_enabled' | 'code_distributions_enabled'
  /** hidden only where the registry says this flag is false (an older registry that does not say keeps it) */
  hiddenWhenRegistryFlagFalse?: 'simulation_enabled' | 'games_enabled'
}

export interface NavGroup {
  /** stable id (open state, tests); never shown */
  id: 'work' | 'agents' | 'organizations' | 'economy' | 'governance' | 'network' | 'developer' | 'administration'
  label: string
  i18nKey: string
  icon: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    id: 'work', label: 'Work', i18nKey: 'nav.groups.work', icon: 'mdi:briefcase',
    items: [
      { name: 'Mission Control', i18nKey: 'nav.items.missionControl', path: '/mission-control', icon: 'mdi:view-grid', color: 'text-blue-600' },
      { name: 'Bridge', i18nKey: 'nav.items.bridge', path: '/bridge', icon: 'mdi:telescope', color: 'text-indigo-400' },
      { name: 'Pocket mode', i18nKey: 'nav.items.pocketMode', path: '/pocket/home', icon: 'mdi:cellphone', color: 'text-cyan-400' },
      { name: 'OurChat', i18nKey: 'nav.items.ourchat', path: '/ourchat', icon: 'mdi:chat', color: 'text-emerald-400', badgeKey: 'chat', authHint: 'Threads, org rooms and the support desk — receipts included' },
      { name: 'The Guild', i18nKey: 'nav.items.guild', path: '/guild', icon: 'mdi:briefcase', color: 'text-yellow-400', authHint: 'Agent work exchange — escrowed bounties, bids, verified pay' },
      { name: 'Workflows', i18nKey: 'nav.items.workflows', path: '/workflows', icon: 'mdi:briefcase', color: 'text-yellow-300', requiresAgent: true, authHint: 'Steps with roles over Guild orders, a ruleset per step, one receipt chain' },
      { name: 'Migrate a system', i18nKey: 'nav.items.migrate', path: '/migrate', icon: 'mdi:database-export', color: 'text-cyan-400', requiresRegistryFlag: 'workflow_templates_enabled', authHint: 'Replace a legacy system: templates, a free dry run, a certified load' },
      { name: 'Proxy', i18nKey: 'nav.items.proxy', path: '/proxy', icon: 'mdi:connection', color: 'text-cyan-300', authHint: 'Bridge a system you keep: the connectors, eight recipes, a spec builder' },
      { name: 'Contracts', i18nKey: 'nav.items.contracts', path: '/contracts', icon: 'mdi:file-document-edit', color: 'text-indigo-600' },
      { name: 'Settlements', i18nKey: 'nav.items.settlements', path: '/settlements', icon: 'mdi:scale-balance', color: 'text-cyan-600', mainframeOnly: true },
      { name: 'Disputes', i18nKey: 'nav.items.disputes', path: '/disputes', icon: 'mdi:gavel', color: 'text-red-600', requiresAgent: true, authHint: 'Requires active agent authentication' },
      { name: 'Approvals', i18nKey: 'nav.items.pocketApprovals', path: '/pocket-approvals', icon: 'mdi:shield-key', color: 'text-emerald-400', authHint: 'IRONKEY delegations, capability permits, panic revoke' },
      { name: 'Cockpit Card', i18nKey: 'nav.items.cockpitCard', path: '/cockpit', icon: 'mdi:card-account-details', color: 'text-rose-400', authHint: 'Underwrite an agent — liability mandates, evidence chain, phone confirms' },
      { name: 'Cockpit Desk', i18nKey: 'nav.items.cockpitDesk', path: '/desk', icon: 'mdi:view-dashboard-variant-outline', color: 'text-rose-300', requiresRegistryFlag: 'cockpit_desk_enabled', authHint: 'Your decisions, agents, denials and conservation on one savable desk' },
      { name: 'Support', i18nKey: 'nav.items.support', path: '/support', icon: 'mdi:lifebuoy', color: 'text-amber-500' },
    ],
  },
  {
    id: 'agents', label: 'Agents', i18nKey: 'nav.groups.agents', icon: 'mdi:robot',
    items: [
      { name: 'Quick onboarding', i18nKey: 'nav.items.onboarding', path: '/onboarding', icon: 'mdi:rocket-launch', color: 'text-teal-600' },
      { name: 'Agent Builder', i18nKey: 'nav.items.agentBuilder', path: '/agent-builder', icon: 'mdi:wrench', color: 'text-orange-600' },
      { name: 'My Agents', i18nKey: 'nav.items.myAgents', path: '/my-agents', icon: 'mdi:robot', color: 'text-green-600' },
      { name: 'Agent Discovery', i18nKey: 'nav.items.agentDiscovery', path: '/discover', icon: 'mdi:magnify', color: 'text-purple-600' },
      { name: 'Leaderboard', i18nKey: 'nav.items.leaderboard', path: '/leaderboard', icon: 'mdi:trophy', color: 'text-yellow-500', authHint: 'Public top-ranked agents by EigenTrust score' },
      { name: 'Pocket Frame', i18nKey: 'nav.items.pocketFrame', path: '/pocket-frame', icon: 'mdi:cellphone-link', color: 'text-cyan-400', authHint: 'Pair your phone + manage push notifications' },
      { name: 'Phone Fabric', i18nKey: 'nav.items.phoneFabric', path: '/phone-fabric', icon: 'mdi:monitor-cellphone', color: 'text-cyan-400', authHint: 'Watch + kill agent phone sessions (computer-use)' },
      { name: 'Gödel Forge', i18nKey: 'nav.items.godelForge', path: '/forge', icon: 'mdi:source-branch', color: 'text-purple-400', authHint: 'Self-improving-agent arena — Evolution Tree, verifier quorums, royalties' },
      { name: 'Game Arena', i18nKey: 'nav.items.gameArena', path: '/games', icon: 'mdi:gamepad-variant', color: 'text-red-500', hiddenWhenRegistryFlagFalse: 'games_enabled' },
    ],
  },
  {
    id: 'organizations', label: 'Organizations', i18nKey: 'nav.groups.organizations', icon: 'mdi:office-building',
    items: [
      { name: 'Organizations', i18nKey: 'nav.items.organizations', path: '/organization', icon: 'mdi:office-building', color: 'text-blue-600' },
      { name: 'Firms', i18nKey: 'nav.items.firms', path: '/firms', icon: 'mdi:office-building', color: 'text-sky-400', authHint: 'Organizations and the work records they publish' },
      { name: 'Community Hub', i18nKey: 'nav.items.communityHub', path: '/community', icon: 'mdi:account-group', color: 'text-violet-500' },
    ],
  },
  {
    id: 'economy', label: 'Economy', i18nKey: 'nav.groups.economy', icon: 'mdi:currency-usd',
    items: [
      { name: 'Become a Backer', i18nKey: 'nav.items.becomeBacker', path: '/become-a-backer', icon: 'mdi:hand-coin-outline', color: 'text-emerald-500', mainframeOnly: true, requiresRegistryFlag: 'fiat_onramp_enabled', authHint: 'Back TheProtocol — receive this frame\'s units + a supporter flare' },
      { name: 'Flare Shop', i18nKey: 'nav.items.flareShop', path: '/flare-shop', icon: 'mdi:store-outline', color: 'text-violet-400', authHint: 'Buy encirclements + broken-machine overlays with this frame\'s own currency' },
      { name: 'My Flare', i18nKey: 'nav.items.myFlare', path: '/flare-manager', icon: 'mdi:shield-star', color: 'text-amber-500', requiresFlare: true, authHint: 'Manage your backer flare — profile + agent assignment' },
      { name: 'Founders Wall', i18nKey: 'nav.items.foundersWall', path: '/founders-wall', icon: 'mdi:trophy-variant', color: 'text-yellow-400', requiresRegistryFlag: 'fiat_onramp_enabled', authHint: 'See the backers powering TheProtocol\'s genesis chapter' },
      { name: 'Locks', i18nKey: 'nav.items.staking', path: '/locks', icon: 'mdi:lock', color: 'text-amber-600', requiresAgent: true, requiresRegistryFlag: 'staking_enabled', authHint: 'Requires active agent authentication' },
      { name: 'Forex Desk', i18nKey: 'nav.items.forex', path: '/forex', icon: 'mdi:swap-horizontal', color: 'text-cyan-400', requiresAgent: true, authHint: 'Move value between your agents — local, cross-registry & cross-frame FX' },
      { name: 'AGORA Desk', i18nKey: 'nav.items.exchange', path: '/agora', icon: 'mdi:chart-candlestick', color: 'text-emerald-400', requiresAgent: true, authHint: 'AGORA: trade org points via order book, launches and distributions' },
      { name: 'AGORA Listings', i18nKey: 'nav.items.stocks', path: '/agora/listings', icon: 'mdi:telescope', color: 'text-emerald-300', authHint: 'Federation listings screener: every market, passport buys on foreign books' },
    ],
  },
  {
    id: 'governance', label: 'Governance', i18nKey: 'nav.groups.governance', icon: 'mdi:bank',
    items: [
      { name: 'Senate Floor', i18nKey: 'nav.items.senateFloor', path: '/senate', icon: 'mdi:bank', color: 'text-yellow-600', requiresAgent: true, authHint: 'Requires active agent authentication' },
      { name: 'Code changes', i18nKey: 'nav.items.codeChanges', path: '/code-changes', icon: 'mdi:code-braces', color: 'text-cyan-500', authHint: 'Changes to the console, decided by the members’ ballot' },
      { name: 'Contributions', i18nKey: 'nav.items.contributions', path: '/contributions', icon: 'mdi:source-branch', color: 'text-cyan-400', requiresRegistryFlag: 'code_distributions_enabled', authHint: 'Your organizations’ release lines: their own changes and ballots' },
      { name: 'Attestations', i18nKey: 'nav.items.attestations', path: '/attestations', icon: 'mdi:certificate', color: 'text-emerald-500', authHint: 'Your ZKP attestations: lifecycle + signed bundles + schedules' },
    ],
  },
  {
    id: 'network', label: 'Network views', i18nKey: 'nav.groups.networkViews', icon: 'mdi:server-network',
    items: [
      { name: 'Federation', i18nKey: 'nav.items.federation', path: '/federation', icon: 'mdi:server-network', color: 'text-indigo-600' },
      { name: 'Announcements', i18nKey: 'nav.items.announcements', path: '/announcements', icon: 'mdi:bullhorn', color: 'text-amber-500', authHint: 'What an administrator made public: open to everyone' },
      { name: 'Federation Peers', i18nKey: 'nav.items.federationPeers', path: '/federation-discover', icon: 'mdi:source-branch', color: 'text-cyan-500', authHint: 'Browse + drill into federation peers, frames, cloud operators' },
      { name: 'Galactic Map', i18nKey: 'nav.items.galacticMap', path: '/galactic-map', icon: 'mdi:map', color: 'text-purple-600' },
      { name: 'AgentWorld', i18nKey: 'nav.items.agentWorld', path: '/agentworld', icon: 'mdi:globe-model', color: 'text-cyan-500' },
      { name: 'Universe', i18nKey: 'nav.items.universe', path: '/universe', icon: 'mdi:creation', color: 'text-indigo-400' },
      { name: 'Operator', i18nKey: 'nav.items.operatorPitch', path: '/operator', icon: 'mdi:server', color: 'text-cyan-500', mainframeOnly: true, authHint: 'Run a registry — backed devs unlock self-service cloud-op provisioning. Sovereign frames request-only.' },
      { name: 'Operator Portal', i18nKey: 'nav.items.operatorPortal', path: '/operator-portal', icon: 'mdi:server-network', color: 'text-cyan-400', mainframeOnly: true, authHint: 'Owner console — your eligibility, your operators, your bundle + credentials' },
      { name: 'Frame Commander', i18nKey: 'nav.items.frameCommander', path: '/frame-commander', icon: 'mdi:globe-model', color: 'text-amber-400', mainframeOnly: true, authHint: 'Request a sovereign frame — your own digital nation under TheProtocol' },
      { name: 'Your frame', i18nKey: 'nav.items.frameKit', path: '/frame-kit', icon: 'mdi:package', color: 'text-amber-300', mainframeOnly: true, requiresRegistryFlag: 'frame_kit_enabled', authHint: 'Follow your frame request and download the frame kit' },
    ],
  },
  {
    id: 'developer', label: 'Developer', i18nKey: 'nav.groups.developer', icon: 'mdi:code-braces',
    items: [
      { name: 'API Tutorials', i18nKey: 'nav.items.apiTutorials', path: '/tutorials', icon: 'mdi:book-open-variant', color: 'text-violet-600' },
      { name: 'API Tester', i18nKey: 'nav.items.apiTester', path: '/api-tester', icon: 'mdi:test-tube', color: 'text-cyan-600' },
      { name: 'Webhooks', i18nKey: 'nav.items.webhooks', path: '/webhooks', icon: 'mdi:webhook', color: 'text-orange-600' },
      { name: 'CI/CD Pipelines', i18nKey: 'nav.items.cicd', path: '/ci-cd', icon: 'mdi:source-branch', color: 'text-green-600' },
      { name: 'Bundles', i18nKey: 'nav.items.bundles', path: '/bundles', icon: 'mdi:archive-outline', color: 'text-indigo-600' },
    ],
  },
  {
    id: 'administration', label: 'Administration', i18nKey: 'nav.groups.administration', icon: 'mdi:shield-account',
    items: [
      { name: 'Developers', i18nKey: 'nav.items.developersAdmin', path: '/admin/developers', icon: 'mdi:account-plus', color: 'text-blue-500', authHint: 'Developer account management' },
      { name: 'Registry Card', i18nKey: 'nav.items.registryCard', path: '/admin/registry-card', icon: 'mdi:radio-tower', color: 'text-cyan-400', authHint: 'Edit this registry\'s v0.3 self-describing federation card' },
      { name: 'Agent Roster', i18nKey: 'nav.items.agentRoster', path: '/admin/agents', icon: 'mdi:account', color: 'text-violet-500', authHint: 'Agent identity and ownership' },
      { name: 'Enforcement', i18nKey: 'nav.items.enforcement', path: '/admin/enforcement', icon: 'mdi:gavel', color: 'text-rose-400', authHint: 'Per-agent economic levers — slashing locked units, offense ladder, suspension, policy + two-man queue' },
      { name: 'Jurisdiction', i18nKey: 'nav.items.jurisdiction', path: '/admin/jurisdiction', icon: 'mdi:scale-balance', color: 'text-teal-400', authHint: 'Declare regulated lifecycle acts and record the state authorizations that unlock them' },
      { name: 'Frame Management', i18nKey: 'nav.items.frameManagement', path: '/frame-management', icon: 'mdi:source-branch', color: 'text-violet-600', mainframeOnly: true, authHint: 'Sovereign frame federation + SF-4/5 data planes' },
      { name: 'OP Management', i18nKey: 'nav.items.opManagement', path: '/operator-management', icon: 'mdi:shield-account', color: 'text-amber-600', mainframeOnly: true, authHint: 'Operator onboarding and lifecycle' },
      { name: 'Federation Tests', i18nKey: 'nav.items.federationTests', path: '/federation-test', icon: 'mdi:server-network', color: 'text-purple-600', mainframeOnly: true, authHint: 'Federation conformance testing' },
      { name: 'Health Monitor', i18nKey: 'nav.items.healthMonitor', path: '/health-monitor', icon: 'mdi:heart-pulse', color: 'text-red-600' },
      { name: 'Command Center', i18nKey: 'nav.items.commandCenter', path: '/command-center', icon: 'mdi:radar', color: 'text-emerald-500', authHint: 'Operator diagnostics & remediation' },
      { name: 'Galactic Command', i18nKey: 'nav.items.galacticCommand', path: '/galactic-command', icon: 'mdi:crosshairs-gps', color: 'text-cyan-400', authHint: 'Fleet cockpit — click a registry on the map, command it' },
      { name: 'EigenTrust', i18nKey: 'nav.items.eigenTrust', path: '/eigentrust-command', icon: 'mdi:brain', color: 'text-purple-500', hiddenWhenRegistryFlagFalse: 'simulation_enabled', authHint: 'Simulation & reputation command center' },
      { name: 'Ironhand', i18nKey: 'nav.items.ironhand', path: '/admin/ironhand', icon: 'mdi:shield-lock', color: 'text-cyan-600', authHint: 'Agent mTLS identity monitor' },
      { name: 'mTLS Theatre', i18nKey: 'nav.items.ironhandTheatre', path: '/ironhand/theatre', icon: 'mdi:map-marker-path', color: 'text-cyan-400', authHint: 'Live cross-frame mTLS identity-travel theatre' },
      { name: 'Consul', i18nKey: 'nav.items.consul', path: '/admin/compliance', icon: 'mdi:shield-search', color: 'text-cyan-400', mainframeOnly: true, authHint: 'Federation compliance monitor + kill switch' },
      { name: 'OPA Policy', i18nKey: 'nav.items.opaConsole', path: '/admin/opa', icon: 'mdi:shield-search', color: 'text-cyan-400', authHint: 'Policy decision evidence + enforce-impact simulator' },
      { name: 'Reactors', i18nKey: 'nav.items.reactors', path: '/admin/reactors', icon: 'mdi:radioactive', color: 'text-emerald-400', authHint: 'Event-driven reactor framework status' },
      { name: 'Releases', i18nKey: 'nav.items.releaseChannel', path: '/admin/release-channel', icon: 'mdi:package', color: 'text-amber-400', authHint: 'Signed release channel: stable releases and hotfixes, the rollout window you schedule' },
      { name: 'Agent Evals', i18nKey: 'nav.items.agentEvals', path: '/admin/evals', icon: 'mdi:clipboard-check-multiple-outline', color: 'text-emerald-400', authHint: 'Scored task batteries for agents — results fold into reputation' },
      { name: 'MCP Tester', i18nKey: 'nav.items.mcpTester', path: '/admin/mcp-tester', icon: 'mdi:bug-check-outline', color: 'text-cyan-400', authHint: 'Full-surface MCP regression sweep — sandbox-only proxy' },
      { name: 'Console Suite', i18nKey: 'nav.items.consoleSuite', path: '/admin/console-suite', icon: 'mdi:monitor-cellphone', color: 'text-cyan-400', authHint: 'The console lifecycle suite: browser runs on a desktop and a phone screen against a sandbox frame' },
      { name: 'Event Ledger', i18nKey: 'nav.items.eventLedger', path: '/admin/events', icon: 'mdi:database-search', color: 'text-violet-400', authHint: 'EventStore explorer — browse the immutable ledger' },
      { name: 'Ledger Forensics', i18nKey: 'nav.items.ledgerForensics', path: '/admin/forensics', icon: 'mdi:shield-search', color: 'text-amber-400', authHint: 'Stuck-funds tracer + AGORA/supply invariants + emission policy console' },
      { name: 'Emission Policy', i18nKey: 'nav.items.emissionPolicy', path: '/admin/emission-policy', icon: 'mdi:database-search', color: 'text-violet-400', authHint: 'Which side may write each event type to the ledger, what the projection counts, and what is wrong' },
      { name: 'CI/CD Fleet', i18nKey: 'nav.items.cicdFleet', path: '/admin/cicd', icon: 'mdi:source-branch', color: 'text-cyan-400', authHint: 'Fleet-wide CI/CD: pipelines, deployments, flags' },
      { name: 'Audit Logs', i18nKey: 'nav.items.auditLogs', path: '/admin/audit-logs', icon: 'mdi:shield-search', color: 'text-amber-400', authHint: 'security_audit_logs — admin action history' },
      { name: 'Marketplace', i18nKey: 'nav.items.adminMarketplace', path: '/admin/marketplace', icon: 'mdi:flag-outline', color: 'text-rose-400', authHint: 'Bundle moderation queue + hide/unhide actions' },
      { name: 'Treasury', i18nKey: 'nav.items.treasury', path: '/admin/treasury', icon: 'mdi:bank', color: 'text-emerald-400', authHint: 'Treasury balance, supply invariant, issuance + fees' },
      { name: 'Fiat Operations', i18nKey: 'nav.items.fiatOps', path: '/admin/fiat-ops', icon: 'mdi:credit-card-settings', color: 'text-emerald-500', mainframeOnly: true, requiresFiat: true, authHint: 'Fiat ops console — overview, pricing, simulator, purchase explorer, manual recovery' },
      { name: 'FX Desk', i18nKey: 'nav.items.fxDesk', path: '/admin/fx', icon: 'mdi:swap-horizontal-bold', color: 'text-amber-400', mainframeOnly: true, authHint: 'Cross-frame FX desk — the pool between the frames\' units, live rate, swap feed + quote simulator' },
      { name: 'AGORA Admin', i18nKey: 'nav.items.exchangeAdmin', path: '/admin/agora', icon: 'mdi:scale-balance', color: 'text-emerald-400', authHint: 'AGORA market command: listings lifecycle, I-X invariants, compliance registry, global halt' },
      { name: 'Webhook Health', i18nKey: 'nav.items.webhookHealth', path: '/admin/webhooks-cluster', icon: 'mdi:webhook', color: 'text-orange-400', authHint: 'Cluster-wide webhook delivery health + failures' },
      { name: 'X-Frame Bridge', i18nKey: 'nav.items.xframeBridge', path: '/admin/bridge', icon: 'mdi:bank-transfer', color: 'text-violet-400', authHint: 'Async + SF-3 cross-frame transfer health' },
      { name: 'Email Studio', i18nKey: 'nav.items.emailStudio', path: '/admin/email', icon: 'mdi:email-outline', color: 'text-cyan-400', authHint: 'Preview transactional + reactor email templates' },
      { name: 'Mail Console', i18nKey: 'nav.items.mailConsole', path: '/admin/mail-fleet', icon: 'mdi:email-fast', color: 'text-cyan-400', authHint: 'Fleet-wide mail posture: who verifies, who can actually send' },
      { name: 'Broadcasts', i18nKey: 'nav.items.broadcasts', path: '/admin/broadcasts', icon: 'mdi:bullhorn', color: 'text-amber-400', mainframeOnly: false, authHint: 'Compose, edit, retract admin broadcasts; read-tracking + WS recipient stats' },
      { name: 'Contributions inbox', i18nKey: 'nav.items.contributionsInbox', path: '/admin/contributions', icon: 'mdi:source-branch', color: 'text-cyan-400', requiresRegistryFlag: 'code_distributions_enabled', authHint: 'Every release line’s changes, across all organizations, in one queue' },
      { name: 'Chat Desk', i18nKey: 'nav.items.chatDesk', path: '/admin/chatdesk', icon: 'mdi:chat', color: 'text-emerald-400', mainframeOnly: false, authHint: 'Support threads + customer-granted reviews; every transcript open is audited' },
      { name: 'Chat Delivery', i18nKey: 'nav.items.chatDelivery', path: '/admin/chat-delivery', icon: 'mdi:email-fast', color: 'text-emerald-400', authHint: 'Per peer, what waits in the cross-registry chat outbox: stuck, late, given up' },
      { name: 'Settlements', i18nKey: 'nav.items.settlementsAdmin', path: '/admin/settlements', icon: 'mdi:scale-balance', color: 'text-violet-400', mainframeOnly: true, authHint: 'Cross-registry dispute compensation slash + payment flows' },
      { name: 'Federation Ops', i18nKey: 'nav.items.federationOps', path: '/federation?tab=operations', icon: 'mdi:server-network', color: 'text-indigo-400', adminFlag: 'federation', authHint: 'Federation Operations tab — drift remediation, license state, BFS reachability' },
      { name: 'Att. Analytics', i18nKey: 'nav.items.attAnalytics', path: '/admin/attestation-analytics', icon: 'mdi:shield-star', color: 'text-emerald-400', authHint: 'ZKP attestation distribution, lifecycle, cadence' },
      { name: 'Canaries', i18nKey: 'nav.items.canaries', path: '/admin/canaries', icon: 'mdi:heart-pulse', color: 'text-cyan-400', authHint: 'Continuous synthetic-transaction monitor' },
      { name: 'ZKP Audit', i18nKey: 'nav.items.zkpAudit', path: '/admin/attestations', icon: 'mdi:shield-check', color: 'text-emerald-500', authHint: 'Cross-platform ZKP attestation audit + force-revoke' },
    ],
  },
]

/** Every entry, once. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)

export function navItemByPath(path: string): NavItem | undefined {
  return NAV_ITEMS.find((i) => i.path === path)
}
