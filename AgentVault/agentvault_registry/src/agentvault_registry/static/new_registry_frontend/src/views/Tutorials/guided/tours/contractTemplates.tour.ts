import type { GuidedTour } from '../tour.types'

// §TOURGAP-2 (2026-08-05) — template AUTHORING shipped in §FEPARITY R4. The smartContracts tour
// covers using contracts; nothing covered publishing the forms other people instantiate.
// Developer-tier, but every authoring rail needs the grant-only contract.template.publish, so
// the tour says so rather than letting people discover it as a 403.
export const contractTemplatesTour: GuidedTour = {
  id: 'contract-templates',
  title: 'Publishing Contract Templates',
  subtitle: 'Write the agreement once, let the network instantiate it',
  icon: 'mdi:file-document-edit',
  accent: '#c084fc',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'A template is a published form', placement: 'center',
      body: 'A contract template is an agreement with its terms, its optional form schema and ' +
        'its milestones, published under a version. Anyone who can see it can **instantiate** ' +
        'it, which creates a real contract from that exact version.\n\nThe institutional value is ' +
        'in the word **exact**: a published version is frozen, so an agreement can never be ' +
        'edited underneath the parties who agreed to it.',
    },
    {
      // The Templates panel is v-show-hidden until its tab is selected, and a route alone
      // never switches a tab on an already-mounted view. This step exists to click it.
      id: 'tab', title: 'Open the template library', anchor: 'contracts-tab-templates',
      placement: 'bottom', route: '/contracts',
      cta: { label: 'Open Templates', do: 'click-anchor' },
      body: 'Contracts, Templates, Analytics. The library lives on the middle tab.',
    },
    {
      id: 'library', title: 'The library', anchor: 'tpl-new', placement: 'bottom',
      cta: { label: 'Open the authoring form', do: 'click-anchor' },
      body: 'Browse, filter by pricing, or narrow to **Mine**. Until recently this tab could ' +
        'only consume templates, and the empty state literally told you to POST to the API to ' +
        'create one. That button is the fix.',
    },
    {
      id: 'create', title: 'Slug, title, visibility, pricing', anchor: 'tpl-create-submit',
      placement: 'top',
      body: 'The slug is your stable identifier and must be lowercase with dashes. Visibility ' +
        'runs private, org, unlisted, public.\n\nPricing is where the thought goes: **free**, ' +
        '**purchase** for a one-time fee before instantiating, or **royalty** which takes a ' +
        'share at settlement and is capped at 500 basis points. The form gates submit on the ' +
        'same rules the server enforces, so an invalid combination is a disabled button rather ' +
        'than a rejected request.',
    },
    {
      id: 'permission', title: 'You need contract.template.publish', placement: 'center',
      body: 'Every authoring rail is gated on the **`contract.template.publish`** permission, ' +
        'which is grant-only. It is not in any ordinary role, though the legacy-full role ' +
        'carries it.\n\nIf you get a refusal here it is a genuine answer about your agent\'s ' +
        'authority, not a bug. Authoring also happens **as your active agent**, so make sure ' +
        'the right one is selected.',
    },
    {
      id: 'version', title: 'Content is versioned, never edited', placement: 'center',
      body: 'Creating the template gives you **v1 as a draft**. Changing content means adding a ' +
        'new draft version with a changelog, not editing what exists.\n\nMetadata is different: ' +
        'title, summary, visibility and pricing can be edited in place, because none of those ' +
        'change what an existing contract agreed to.',
    },
    {
      id: 'publish', title: 'Publishing is irreversible', placement: 'center',
      body: 'Publishing **freezes** a version permanently. It cannot be edited and it cannot be ' +
        'unpublished, and the confirmation dialog says so before you commit.\n\nThat is not ' +
        'caution for its own sake. Contracts made from a version must keep referring to the ' +
        'terms they were agreed under, so the freeze is what makes the whole library ' +
        'trustworthy. Need a change? New version.',
    },
    {
      id: 'fork', title: 'Forking records lineage', placement: 'center',
      body: 'Fork any template you can see and you get your own line, starting **private and ' +
        'free**, with royalty deliberately **not** inherited: you price your own work.\n\nThe ' +
        'link back to the original is recorded, so provenance survives even though the ' +
        'commercial terms do not.',
    },
    {
      id: 'outro', title: 'Why bother publishing one', placement: 'center',
      body: 'Because the alternative is every agent negotiating the same agreement from scratch, ' +
        'badly. A good template is reusable institutional knowledge, and the settle rate shown ' +
        'on each card tells readers whether yours actually works in practice.\n\nNext: the ' +
        '**Agent-to-Agent Contracts** tour for what happens after one is instantiated.',
    },
  ],
}
