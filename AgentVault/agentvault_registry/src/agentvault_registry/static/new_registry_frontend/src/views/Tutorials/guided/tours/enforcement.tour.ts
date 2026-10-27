import type { GuidedTour } from '../tour.types'

// §TOURGAP-2 (2026-08-05) — the enforcement console shipped in §FEPARITY R2 with a sidebar
// entry but no tour. The existing opEnforcement tour visits /admin/agents and /admin/ironhand,
// NOT this console. Operator series: admin + the granular `enforcement` flag.
export const enforcementTour: GuidedTour = {
  id: 'op-enforcement-console',
  title: 'Operator: The Enforcement Console',
  subtitle: 'Per-agent economic levers, and the gates that stop you firing them by accident',
  icon: 'mdi:gavel',
  accent: '#fb7185',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'enforcement',
  steps: [
    {
      id: 'intro', title: 'The levers you hope never to pull', placement: 'center',
      body: 'An agent misbehaves. You need to be able to respond, and you need the response to ' +
        'be **proportionate, recorded and reversible where it should be**.\n\nUntil recently ' +
        'every one of these actions existed only as an API call, which meant the people most ' +
        'likely to need them in a hurry were the least equipped to use them. This console is ' +
        'that gap closed.',
    },
    {
      id: 'agent', title: 'Pick your subject', anchor: 'enf-agent', placement: 'bottom',
      route: '/admin/enforcement',
      body: 'Everything here acts on **one named agent**. Paste a DID, or arrive here from the ' +
        'agent roster, which deep-links straight into this view with the subject already filled ' +
        'in.\n\nThe status panel shows the agent\'s current enforcement state and offense count ' +
        'before you touch anything.',
    },
    {
      id: 'slash', title: 'Slashing is preview-gated on purpose', placement: 'center',
      body: 'Slashing takes units out of an agent\'s bond and balance. So the console will not let you ' +
        'do it blind: the **Preview** call runs first and shows you exactly what would happen, ' +
        'and only then does the execute control become available.\n\nThe reason is not ' +
        'ceremony. A slash on the wrong DID is not something an apology fixes, and a preview ' +
        'costs you four seconds.',
    },
    {
      id: 'ladder', title: 'The offense ladder', placement: 'center',
      body: 'Recording an offense is usually the right first move rather than jumping to a ' +
        'penalty. Offenses accumulate against the agent and the configured policy decides what ' +
        'escalation looks like, so the ladder is applied consistently instead of depending on ' +
        'who happened to be on shift.',
    },
    {
      id: 'pending', title: 'Two-man rule', anchor: 'enf-pending', placement: 'top',
      body: 'Some actions land in a **pending queue** rather than executing immediately, and ' +
        'need a second admin to approve them.\n\nRead that carefully: **approving here EXECUTES ' +
        'the action.** It is not a rubber stamp on something that already happened. Reject is ' +
        'equally final.',
    },
    {
      id: 'policy', title: 'The policy itself', anchor: 'enf-policy', placement: 'top',
      body: 'The live enforcement policy for this registry, editable as JSON with parse and ' +
        'dirty-state gating so you cannot save something malformed.\n\nThis is the document ' +
        'that decides what the ladder does. Changing it changes how every future offense is ' +
        'treated, which makes it the highest-leverage and least-dramatic control on the page.',
    },
    {
      id: 'reasons', title: 'Every mutator wants a reason', placement: 'center',
      body: 'Slash, pause payouts, suspend, reinstate: each one goes through a single ' +
        'confirmation dialog that **requires a written reason** before it will proceed.\n\nThat ' +
        'reason lands in the audit trail. Six months from now, when somebody asks why this ' +
        'agent was penalised, the answer should not depend on whether anyone remembers.',
    },
    {
      id: 'outro', title: 'Enforcement is a record, not a mood', placement: 'center',
      body: 'Preview before you slash. Prefer the ladder to the hammer. Write the reason as if ' +
        'a stranger will read it, because one will.\n\nNext: **Operator: Watchtower Basics** for ' +
        'the views that tell you an agent needs attention in the first place.',
    },
  ],
}
