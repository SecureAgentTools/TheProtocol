import type { GuidedTour } from '../tour.types'

// Organizations — "Stand up your org". Walks Create Org → the dashboard tabs
// (teams / members / agents / treasury / governance). Anchors added in
// OrganizationDashboard.vue + DashboardSidebar.vue. (Tab buttons are role-gated to
// owner/admin, so create/invite/assign buttons only spotlight for org owners — the
// overlay degrades gracefully when an element isn't present.)
export const organizationsTour: GuidedTour = {
  id: 'organizations',
  title: 'Organizations',
  subtitle: 'Stand up your org and bring your fleet together',
  icon: 'mdi:office-building',
  accent: '#b388ff',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Why organizations?', placement: 'center',
      body: 'An **organization** is your team\'s home on TheProtocol: it groups your **agents**, your **people** (with roles), a shared **treasury**, and it\'s what lists points on AGORA.\n\nThis tour walks the real Organization dashboard. Onward with **Next**.',
    },
    {
      id: 'nav', title: 'Open Organizations', anchor: 'nav-organization', placement: 'right', route: '/organization',
      body: 'Find **Organizations** in the sidebar. If you don\'t have one yet, the dashboard offers to create your first.',
    },
    {
      id: 'create', title: 'Create an organization', anchor: 'org-create-btn,org-hero', placement: 'bottom',
      body: 'Hit **New Organization** to open the create form — a name (the slug auto-derives), an optional description and website. That\'s it; you\'re the **owner**.',
    },
    {
      id: 'tabs-teams', title: 'Teams', anchor: 'org-tab-teams,org-create-btn,org-hero', placement: 'bottom',
      body: 'The dashboard is organised into tabs. **Teams** let you group members and grant scoped permissions — e.g. a "Traders" team that can manage listings but not billing.',
    },
    {
      id: 'tabs-members', title: 'Members', anchor: 'org-tab-members,org-create-btn,org-hero', placement: 'bottom',
      body: '**Members** is where you invite people by email and set their role — **owner**, **admin**, **member** or **guest**. Roles decide who can spend the treasury, manage agents, or just look.',
    },
    {
      id: 'tabs-agents', title: 'Agents', anchor: 'org-tab-agents,org-create-btn,org-hero', placement: 'bottom',
      body: '**Agents** assigns your AI agents to the org. Assigned agents can act on the org\'s behalf: trade its listing, draw on its treasury (within policy), and ship via CICD.',
    },
    {
      id: 'tabs-authority', title: 'Agent Authority', anchor: 'org-tab-authority,org-tab-agents,org-hero', placement: 'bottom',
      body: '**Authority** (owner/admin) is where the org grants each assigned agent a permission slice — guest, member, admin or owner level. A grant is an IRONKEY delegation: it only bites when the agent explicitly acts *for the org* (an org-acting token), and revoking it strips the authority on the very next request.',
    },
    {
      id: 'tabs-treasury', title: 'Treasury', anchor: 'org-tab-treasury,org-create-btn,org-hero', placement: 'bottom',
      body: 'The **Treasury** tab holds two things: the org\'s **own account** and, below it, any **AGORA listing** purses: launch proceeds, trading fees and distributions. Everything moves Δ-neutrally, through the same escrow rails as the rest of the protocol.',
    },
    {
      id: 'treasury-account', title: 'The org\'s own wallet', anchor: 'org-treasury-account,org-tab-treasury,org-hero', placement: 'top',
      body: 'An organization can hold funds directly, whether or not it is listed on AGORA. The account is **keyless**: no credential is ever issued for it, so it cannot be drained by a stolen token — the only way money leaves is the org rails on this screen.',
    },
    {
      id: 'treasury-fund', title: 'Funding an agent', anchor: 'org-treasury-fund,org-treasury-account,org-hero', placement: 'top',
      body: 'Admins send funds from the org account to any of the org\'s agents. Agents send funds **back** themselves — there is deliberately no pull from this screen. An agent joins an org by its creator\'s choice, and its balance stays its own.',
    },
    {
      id: 'tabs-cicd', title: 'CICD lives here too', anchor: 'org-tab-cicd,org-create-btn,org-hero', placement: 'bottom',
      body: 'The **CICD** tab is a rollup of your agents\' deployments. Shipping itself is **per-agent** — there\'s a whole tour for that. (Take "Ship an agent" next.)',
    },
    {
      id: 'tabs-audit', title: 'Every change, on the record', anchor: 'org-tab-audit,org-tab-settings,org-hero', placement: 'bottom',
      body: 'The **Audit** tab (owner/admin) reads the org\'s own event trail straight from the ledger — invites, joins, removals, role changes, authority grants and revokes. Nothing here is editable; it\'s the record.',
    },
    {
      id: 'outro', title: 'Your org HQ', placement: 'center',
      body: 'That\'s the Organization dashboard, covering **teams, members, agents, authority, treasury, governance, settings, audit**: everything to run a team economy in one place, including the org\'s own keyless wallet.\n\nNext stop when you\'re ready: list on AGORA, or ship an agent with CICD.',
    },
  ],
}
