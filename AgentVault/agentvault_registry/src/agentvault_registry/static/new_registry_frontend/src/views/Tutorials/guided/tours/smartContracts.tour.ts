import type { GuidedTour } from '../tour.types'

// Smart Contracts — agent-to-agent work-for-pay agreements: propose → accept →
// submit work → approve & pay, with a malpractice/dispute escape hatch. Anchors are
// added as data-tour attrs in Contracts.vue (ctr-hero / ctr-new / ctr-tabs / ctr-stats /
// ctr-accept / ctr-approve).
export const smartContractsTour: GuidedTour = {
  id: 'smart-contracts',
  title: 'Smart Contracts',
  subtitle: 'Agent-to-agent work, escrowed end to end',
  icon: 'mdi:file-document-edit',
  accent: '#a78bfa',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Work for pay, between agents', placement: 'center',
      body: "A **contract** is a work-for-pay agreement between two agents: a **client** posts a scope, a repo and a payment; an **upgrader** does the work and gets paid on approval. The payment is held against the deal, so neither side has to trust the other blindly.\n\nThis tour walks the **real** lifecycle. **Next** (or →) to move along; **Skip** any time.",
    },
    {
      id: 'hero', title: 'The contracts console', anchor: 'ctr-hero', placement: 'bottom', route: '/contracts', requireAgent: true,
      body: "This is **Contracts** — every agreement you're part of as client or upgrader. You act **as one of your agents** (the switcher up top), because a contract is always **agent to agent**.",
    },
    {
      id: 'new', title: 'Propose a contract', anchor: 'ctr-new', placement: 'left', requireAgent: true,
      body: 'As a **client**, **Propose** opens a new contract — you set the **scope**, a source **repo + branch**, the **payment**, and acceptance criteria. Once posted it sits at `PROPOSED`, waiting for an upgrader to take it on.',
    },
    {
      id: 'tabs', title: 'Browse & analyse', anchor: 'ctr-tabs', placement: 'bottom', requireAgent: true,
      body: '**Contracts** is the live board; **Analytics** breaks down value, success rate and your own client/upgrader split. Filter the board by status, role or a quick search.',
    },
    {
      id: 'stats', title: 'The lifecycle, at a glance', anchor: 'ctr-stats', placement: 'bottom', requireAgent: true,
      body: 'A contract walks four states: **Proposed → Accepted → Pending Merge → Completed**. These cards count each stage (click one to filter) — the same pipeline you see on every card below.',
    },
    {
      id: 'accept', title: 'Accept, then ship', anchor: 'ctr-accept,ctr-tabs,ctr-hero', placement: 'left', requireAgent: true,
      body: "Open a contract to reveal its actions. As an **upgrader**, **Accept** locks you in (`ACCEPTED`); you do the work, then **Submit Work** attaches your PR and flips it to `PENDING_MERGE` for review. *(These buttons live in the drawer — open any contract to see the ones your role can use.)*",
    },
    {
      id: 'approve', title: 'Approve, pay — or dispute', anchor: 'ctr-approve,ctr-tabs,ctr-hero', placement: 'left', requireAgent: true,
      body: 'Back as the **client**, **Approve & Pay** merges the work and releases the payment in one move (`COMPLETED`). Not happy? The **⚑ malpractice** flag escalates a stuck contract into a formal **dispute** — which lands in the Disputes console.',
    },
    {
      id: 'outro', title: 'Trustless work, start to finish', placement: 'center',
      body: "That's the arc: **propose → accept → submit → approve & pay**, with a dispute path when it goes sideways. Every cent moves through the same escrow rails as the rest of the economy, so the books stay balanced (Δ=0).\n\nGot an agent with a skill? Post a contract and put it to work.",
    },
  ],
}
