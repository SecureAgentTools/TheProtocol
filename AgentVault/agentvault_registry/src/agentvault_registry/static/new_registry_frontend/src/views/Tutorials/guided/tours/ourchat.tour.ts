import type { GuidedTour } from '../tour.types'

/**
 * §CHATCOHERE A2 (2026-09-01) — the tour OurChat never had.
 *
 * Measured before it was written: 38 registered tours, and `grep -l ourchat` over
 * the whole tours directory returned NOTHING. Every lesser surface in the product
 * is taught; the one the Commander could not read was not. The reason was
 * structural rather than an oversight — no OurChat surface carried a single
 * `data-tour` attribute, so there was nothing a tour could point at.
 *
 * What it has to teach is narrower than "here is a button". A cold start showed
 * the real gap: typing `hello — what can you do?` into a paid thread does not say
 * hello, it opens a 2 BVT purchase confirmation. That is correct behaviour on a
 * rail where answers cost money, and completely surprising if nobody told you.
 * So the spine of this tour is the money model — what a thread IS, when a price
 * appears, what confirms, and what arrives afterwards — not a feature list.
 *
 * ⚠ NO `requireFlag`. §COCKPITA: it is checked as an RBAC ADMIN action, and
 * setting one here would lock the tour for exactly the people it is written for.
 * ⚠ Every anchored step points at an element that exists on an EMPTY account —
 * the find door, the empty state, the cast, the hosting line, the composer, the
 * speaker chip. Nothing anchors to a message, a card or a receipt, because a new
 * reader has none and a missing anchor degrades to a centred card in silence.
 */
export const ourChatTour: GuidedTour = {
  id: 'ourchat',
  title: 'OurChat',
  subtitle: 'Talking to agents that work for a fee — and reading what comes back',
  icon: 'mdi:chat',
  accent: '#4fd8c4',
  estMinutes: 6,
  steps: [
    {
      id: 'intro', title: 'A chat where the other side charges', placement: 'center', route: '/ourchat',
      body: 'This looks like a messaging app and mostly behaves like one — but some of the ' +
        'people you talk to here are **agents that work for a fee**.\n\nThat one fact explains ' +
        'nearly everything that is otherwise surprising: why a price appears, why some messages ' +
        'ask you to confirm, and why an answer arrives looking like a **receipt** rather than a ' +
        'reply. Nothing here moves money on its own; you will always see the number first.',
    },
    {
      // §TOURTRUTH (2026-09-02) — list/cast/find anchor the EMPTY state (a person with threads never sees them); hosting/speaker/composer need an OPEN thread. Skipped when absent.
      id: 'list', optional: true, title: 'Threads, and a first move', anchor: 'ourchat-empty', placement: 'right',
      waitMs: 15000,
      body: 'Your conversations live down this side. While you have none, this panel does the ' +
        'introducing instead.\n\n⚠ If you already have threads, this panel is replaced by them — ' +
        'that is the same space doing its ordinary job.',
    },
    {
      id: 'cast', optional: true, title: 'Who answers, and what they charge', anchor: 'ourchat-cast', placement: 'right',
      body: 'These are agents this registry will stand behind as a first move: each one has ' +
        'described what it does, and none of them is known to be unreachable.\n\nThe number ' +
        'beside a name is its **price per answer**, with its currency. If that currency is not ' +
        'the one your registry settles in, the row says so — the agent is still hireable, it ' +
        'just converts.',
    },
    {
      id: 'find', optional: true, title: 'Everyone else', anchor: 'ourchat-find', placement: 'bottom',
      body: 'The suggestions are a starting point, not the population. **Find someone to talk ' +
        'to** searches agents and people across the federation, including free ones and agents ' +
        'homed on other registries.',
    },
    {
      id: 'hosting', optional: true, title: 'Who can read this', anchor: 'ourchat-hosting', placement: 'bottom',
      route: '/ourchat', waitMs: 15000,
      body: 'Open any thread and this line is the first thing in it. It names the registry ' +
        'that **hosts** the conversation, and it is there because that operator can read it.\n\n' +
        'This is not end-to-end encrypted and the product does not pretend otherwise. If a ' +
        'retention timer is set, it is shown here too.',
    },
    {
      id: 'speaker', optional: true, title: 'Who you are speaking as', anchor: 'ourchat-speaker', placement: 'top',
      body: 'You can speak as **yourself** or as one of **your agents**. It matters, because ' +
        'the agent is what holds the money: a paid call is charged to the agent you are acting ' +
        'as, in that agent\'s own currency, not to you personally.\n\nIf the chip says no agent ' +
        'is acting, a paid call has no purse to draw on yet.',
    },
    {
      id: 'composer', optional: true, title: 'Plain words are a paid call here', anchor: 'ourchat-composer',
      placement: 'top',
      body: 'In a thread with a paid agent, **what you type is the ask** — there is no separate ' +
        '"buy" button. Type a question, press send, and a sheet appears with the price, what ' +
        'you hold, and two choices.\n\nNothing has moved at that point. **Call** is the moment ' +
        'money is authorized; **Cancel** costs nothing. The placeholder in the box always ' +
        'carries the per-answer price so it is never a surprise.',
    },
    {
      id: 'commands', title: 'The slash commands', placement: 'center',
      body: 'Type **/help** in any thread for the full list, grouped by what it needs: some ' +
        'commands work everywhere, some need an agent on the other side, some only make sense ' +
        'in an organization room. Anything that does not apply where you are standing is shown ' +
        'dimmed **with the reason**, and groups where nothing applies are folded away.\n\n' +
        'Three worth knowing on day one: **/quote** prices an agent before you commit, ' +
        '**/balance** says what the acting agent holds, and **/audit** runs a background check ' +
        'from public data and posts nothing.',
    },
    {
      id: 'cards', title: 'Answers arrive as records', placement: 'center',
      body: 'When a paid call completes, what lands in the thread is not prose — it is a ' +
        '**card**: what was asked, what came back, what was charged and in which currency.\n\n' +
        'Some cards can only be written by the rails themselves — a service result, a signed ' +
        'holding, a settlement. That restriction is the point: a receipt anyone could type ' +
        'would not be worth reading. A call that fails says so and states plainly that nothing ' +
        'was charged.',
    },
    {
      id: 'outro', title: 'The short version', placement: 'center',
      body: 'You ask in your own words. You see the price and what you hold. You confirm, or ' +
        'you do not. What comes back is a record you can check.\n\nIf you ever see a number ' +
        'here without a currency beside it, or a price you cannot trace to a card, that is a ' +
        'bug worth reporting — every figure in this surface is supposed to say where it came ' +
        'from.',
    },
  ],
}
