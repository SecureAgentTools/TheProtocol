import type { GuidedTour } from '../tour.types'

// §COCKPITA (2026-08-31) — the Cockpit Desk shipped through P0-P8b with no tour, and then
// gained two channels and a live ledger on registry-a. This is its walkthrough.
//
// The tour's job here is unusual: the desk's whole argument is that FOUR facts about an
// agent are different facts, and that a surface which folds them into one light is lying.
// A tour that only said "here is a pane" would undo that. So the steps teach the
// DISTINCTIONS, and the anchors are the shell and the panes themselves (which render
// whatever the data says) rather than any row, so it never strands on an empty board.
export const cockpitDeskTour: GuidedTour = {
  id: 'cockpit-desk',
  title: 'The Cockpit Desk',
  subtitle: 'Consent per decision, and the four different questions about a running agent',
  icon: 'mdi:view-dashboard-outline',
  accent: '#7c9cff',
  estMinutes: 9,
  // ⚠ NO `requireFlag`. It is checked as an RBAC ADMIN action (`can(flag)`), and there is
  // no 'cockpit' admin action — setting it would have LOCKED this tour for everyone,
  // including the liable human it is written for. The desk is a DEVELOPER surface: the
  // route guard already owns whether it can be opened on this registry.
  // §FESUITE: and the HUB owns whether it is offered. Without this the hub offered the tour on every frame, and where
  // the desk is switched off its first stop redirected home and every later stop pointed at nothing.
  requiresRegistryFlag: 'cockpit_desk_enabled',
  steps: [
    {
      id: 'intro', title: 'A desk, not a dashboard', placement: 'center', route: '/desk',
      body: 'Most dashboards answer "is everything fine?" with one colour. This one refuses to.\n\n' +
        'The Cockpit Desk exists because an autonomous agent acts **in your name**, and the ' +
        'person who is liable for that has to be able to see what is happening and say yes or ' +
        'no to the things that matter. Every pane here is built on a rail that already exists — ' +
        'nothing on this desk invents a number.',
    },
    {
      id: 'shell', title: 'Panes on one bus', anchor: 'cockpit-desk', placement: 'bottom',
      body: 'Every pane you see shares **one** WebSocket subscription. That is a deliberate ' +
        'constraint: a desk where each tile opened its own socket would look identical and cost ' +
        'twelve connections.\n\nEach pane also states its own freshness — LIVE (pushed), POLL ' +
        '(re-read on a stated interval), or ONCE (read at mount). A number with no stated ' +
        'freshness is a number you cannot act on.',
    },
    {
      id: 'layouts', title: 'Layouts, and honest absence', anchor: 'cockpit-layouts', placement: 'bottom',
      body: 'Triage, Money, Incident and Build are starting points; you can edit and save your own.\n\n' +
        'A saved layout names panes as strings, so a pane that **cannot** exist on this ' +
        'deployment renders a tile saying so and why — rather than quietly vanishing. A door ' +
        'that is silently not there is worse than a door that says it is locked.\n\n' +
        'Press **Arrange** to add, move or remove panes — and to **rename or delete** a layout ' +
        'you saved. The four starters are built into the registry, so they cannot be renamed or ' +
        'deleted; the panel tells you that instead of just leaving the buttons out.',
    },
    {
      // §TOURTRUTH (2026-09-02) — each of these spotlights ONE pane; a person whose desk does not carry it is walked past, not stranded on a card about a pane they cannot see (measured: 8 of 14 steps dangling on a default four-pane desk).
      id: 'agents', optional: true, title: 'Four questions, never one light', anchor: 'cockpit-agents', placement: 'right',
      body: 'This is the pane the rest of the desk is measured against. For each agent it answers ' +
        'four **separate** questions, because folding them together is how a dashboard misleads:\n\n' +
        '**Enforcement** — `active` / `suspended` / `revoked`. Set by the enforcement rail. ' +
        'Not "is it running", and not yours to change.\n\n' +
        '**Deployment** — whether this registry\'s CI/CD ever shipped it. Most agents here read ' +
        '*no deployment record*, and that is honest: they are run as containers, not deployed ' +
        'through the registry.\n\n' +
        '**Runtime** — is it up **right now**, from two directions: it called us, or we probed ' +
        'it. An old probe is reported as *stale*, never repeated as if it were current.\n\n' +
        '**Traffic** — an agent nobody has ever called returns 0 requests and 0% success, which ' +
        'is byte-identical to one failing everything. So it says *no traffic recorded* instead ' +
        'of accusing a healthy agent.',
    },
    {
      // §COCKPITPOLISH P5c — the pane exists because "which of my agents is actually
      // running" had no answer on this desk. The step's real job is the honesty note:
      // anyone reading the word "heartbeat" will assume a protocol we do not have.
      id: 'heartbeat', optional: true, title: 'Who is calling home', anchor: 'cockpit-heartbeat', placement: 'bottom',
      body: 'Ranked by **when each agent last called this registry**, most recent first.\n\n' +
        'One thing to be clear about, because the word invites the wrong assumption: there is ' +
        'no separate heartbeat protocol here. `POST /agents/heartbeat` only stamps the same ' +
        'field that **any** authenticated call from the agent stamps. So this measures exactly ' +
        'one thing — *it reached in, with its own credentials, this recently* — and the pane ' +
        'says so on screen rather than letting the title imply more.\n\n' +
        'Beside it sits the other direction: what **our** probe found when it called the ' +
        'agent\'s published address. The two disagreeing is the useful case. An agent calling ' +
        'in every minute that we cannot reach has a broken published address; one we can reach ' +
        'that has stopped calling has quietly stopped working.\n\n' +
        'The chips filter — Live, Quiet, All — and because a filter **hides** rows, the pane ' +
        'always tells you how many it is not showing.',
    },
    {
      id: 'ledger', optional: true, title: 'Your live ledger', anchor: 'cockpit-ledger', placement: 'left',
      body: 'The same event stream Mission Control draws, scoped to **your** agents and with the ' +
        'same payload inspector.\n\nThe scope is the interesting part: "mine" is computed from ' +
        'your whole fleet of agent identities, not from whichever page of agents happened to ' +
        'load. That distinction once made this filter true for 200 agents out of 4,098 — and ' +
        'the 200 it had were the wrong ones.\n\nClick any row to inspect the raw event.',
    },
    {
      id: 'channels', optional: true, title: 'Two channels, kept apart', anchor: 'cockpit-channels', placement: 'top',
      body: 'On the left, what your agents say they are doing while they work. Pure observation — ' +
        'nothing on that side can act.\n\nIf the buffer cannot be read it says so, because ' +
        '"no agent reported anything" and "we could not look" are different facts that would ' +
        'otherwise render identically.',
    },
    {
      id: 'instruct', optional: true, title: 'The one control that acts', anchor: 'cockpit-instruct', placement: 'left',
      body: 'Everything else on this desk watches. **This** sends an instruction to a running ' +
        'agent, over the agent\'s own **A2A** interface — the standard address its card ' +
        'advertises, never a URL typed here.\n\nIt is owner-only, and every instruction is ' +
        'recorded against your account whether it arrives or not: an instruction that failed to ' +
        'land is still one you issued.\n\nAgents that publish no A2A interface show you **why** ' +
        'the box is disabled instead of offering a button that would post into nothing.',
    },
    {
      // §COCKPITPOLISH P7.1 — the audit rail had been writing since §COCKPITA and nothing
      // rendered it. The step is short on purpose: its point is that failures are here.
      id: 'instructions', optional: true, title: 'What you told them, and whether it landed',
      anchor: 'cockpit-instructions', placement: 'top',
      body: 'Every instruction you send is written to the audit log whether it arrives or not, ' +
        'and this is where you read them back.\n\n' +
        'Undelivered attempts are shown **louder** than delivered ones. A history that quietly ' +
        'listed only the successes would look perfect on exactly the day the loop broke.\n\n' +
        'What is not here is the instruction **text**: the record keeps its length, never its ' +
        'content. The pane says that rather than leaving you to wonder whether it was lost.',
    },
    {
      id: 'consent', title: 'Where consent actually happens', placement: 'center',
      body: 'The Decisions pane is the heart of the desk: when an agent needs authority you have ' +
        'not already given, it parks and asks **you**.\n\nThe ask shows what will happen in ' +
        'units and counterparties, records what was on your screen when you approved it, and ' +
        'refuses a signature that arrives faster than a human could have read it. Approve, deny, ' +
        'or let it expire — an expiry is a denial, and it is receipted like one.',
    },
    {
      // §COCKPITFIT — the pane he reacted to hardest had an anchor and no step.
      id: 'denials', optional: true, title: 'What was refused while you slept', anchor: 'cockpit-denials',
      placement: 'left',
      body: 'Consent is the half you see. This is the half you do not: every action an agent ' +
        'tried to take and **could not**, grouped by why.\n\nThe reasons are written as ' +
        'sentences because the enum is not the point — "a delegated token reached past the ' +
        'authority it was given" is a confused deputy being stopped at the gate, with no human ' +
        'in the loop and nothing to undo. A fleet with zero refusals is not a well-behaved ' +
        'fleet; it is a fleet whose gates were never asked a question.\n\nEach group carries ' +
        'how many agents it spans and how recent the last one was, so you can tell a historical ' +
        'burst from something happening now.',
    },
    {
      id: 'receipts', optional: true, title: 'One decision, one receipt', anchor: 'cockpit-receipts',
      placement: 'top',
      body: 'The aggregate above answers "how often". This answers "**which one**".\n\nEvery ' +
        'time an agent needed authority you had not already given, there is a row here: what ' +
        'was asked, in what units, and what you did about it. An expiry is shown as **a denial ' +
        'by silence**, because that is what it was — not a missing answer.\n\nThis is the ' +
        'artefact to reach for when someone asks who agreed to a thing, and what they were ' +
        'shown at the moment they agreed.',
    },
    {
      // ⚠ CENTRE, no anchor: both panes live only on the Trading layout, and an anchor
      // that is not on the active layout degrades to a centred card ANYWAY — silently.
      // Saying so out loud beats a step that looks broken on four layouts out of five.
      id: 'trading', title: 'Holdings belong to an agent', placement: 'center',
      body: 'The **Trading** layout adds two panes with a distinction worth knowing.\n\n' +
        '*Market* is public: listings, the last trades, and how stale that tape is — it will ' +
        'tell you the last trade was four days ago rather than implying a quiet market is a ' +
        'live one.\n\n*Your holdings* is the **only** pane on this desk that follows the ' +
        'agent in the header switcher. Everything else answers for your whole account. Points ' +
        'are held by an agent, not by you, so the pane asks you to pick one instead of ' +
        'summing things that do not belong together.',
    },
    {
      id: 'outro', title: 'What to do with it', placement: 'center',
      body: 'Put **Incident** on screen when something is wrong: fleet health beside your own ' +
        'agents, their runtime, and your live ledger.\n\nUse **Build** while you are wiring an ' +
        'agent up: the channels pane will show its progress the moment it starts reporting.\n\n' +
        'And if a pane ever shows you a number you cannot explain, that is a bug in the pane, ' +
        'not in your reading of it. Every figure on this desk is supposed to name where it came ' +
        'from.',
    },
  ],
}
