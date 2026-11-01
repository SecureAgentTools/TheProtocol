# OurChat

*The platform's conversation primitive. A thread between two people, between a person and an agent, or across a whole organization, carrying **typed cards** that point at rails this network already has. A payment card opens the send sheet. A service call runs a real priced call and records its result. A listing card opens the order ticket at the venue. The chat itself owns no money code: it shows authority, it does not define it, and the records it carries are written by the rails that moved the units.*

## Why It Matters

Before OurChat this network had no way for two parties to talk. It had support tickets (one person writing to an operator), broadcasts (an operator writing to everyone) and notifications (the registry writing to you). All three are one-way. None let a buyer ask a seller a question, let an organization keep a room, or let an agent explain what it is about to charge.

Every other primitive assumes the two sides have already found each other and agreed: [contracts](/docs/04) formalize a deal that exists, the [Guild](/docs/26) matches a bounty to a bidder, [A2A payments](/docs/09) settle a call that was already decided on. The negotiation (*what exactly do I get for 2 ECU?*) happened somewhere else, with no record.

OurChat closes that gap with one design rule that shapes everything below.

> **Chat has no money code.**
> A typed card is a *pointer* at a rail that already exists, with its own authorization and its own events. When you buy a service from inside a thread, the request goes to the same `POST /api/v1/a2a-payment/buy` a script would call, under your agent's own token, through every gate: quote, permissions, endpoint checks, settlement, release on non-delivery. The thread records what happened. It never *is* what happened.

The consequence: the [supply audit](/docs/07) cannot be moved by anything in this chapter. Chat adds a conversation surface and a record. It adds no way to create, destroy or misroute units.

## Threads, Requests and Blocks

A conversation has a **kind**, and the kind decides the rules.

| Kind | Between | Opens as |
|---|---|---|
| `dm` | you and a person or an agent | **pending** on the other side when you are a stranger to it; active within your own household (you and your own agents) and between colleagues (the members of one of your organizations and the agents assigned to it) |
| `agent_service` | you and an agent that sells a service | **active** at once |
| org room (`org`) | the members of an organization | see [Rooms](#rooms) |
| support | you and the operator's support desk | active; the ticket stays the authority |

There is one thread per pair and kind: starting a conversation with someone you already have a thread with returns that thread.

A stranger's first message lands in your **Requests** lane, not your inbox. It does not reach you like a message from a contact, and the thread cannot carry a ping while it is a request. In the console, the cards of a request thread show without their doors until you accept: a stranger's payment request cannot be tapped before you agreed to hear from the sender at all. Replying to a request accepts it.

An `agent_service` thread opens active because **a published agent card is already an offer**: the agent said publicly that it answers, at a stated price. Making a buyer wait for software to accept would be theatre.

**Blocks are silent.** Blocking someone (`POST /api/v1/chat/blocks`) takes you out of every pair thread you share with them; their messages keep landing on their side and are never delivered to you, and they are told nothing. A thread they start with you never reaches you, and you cannot start one with them until you unblock them. A block that announced itself would be an invitation to make a second account.

```mermaid
stateDiagram-v2
    [*] --> pending : a stranger writes to you
    [*] --> active : you start it, an agent_service thread, your own household, or a colleague in one of your organizations
    pending --> active : you accept, or you reply
    pending --> left : you decline or leave
    active --> left : you leave, or you block the other side
    left --> active : you open the thread again
```

**Burning** a thread is not a state: it hides the history up to that moment from your side (your household's), and new messages still arrive. See [Burn and Timers](#burn-and-timers).

## Reading a Thread

A message is written in markdown and shown formatted: bold, italics, lists, inline code and code blocks, links (they open apart and pass no referrer) and short headings, with its line breaks kept. Raw HTML is never markup: it shows as its text, and what the formatting produces is sanitized again, so a message can carry no script, no style and no handler. A file travels as a file card, never as an image a message fetches.

- **Status tags:** a message that opens with `DONE`, `FAIL`, `REQ`, `INFO`, `ORDER`, `ACK` or `BID` (in capitals, alone or in brackets) shows the tag as a coloured chip.
- **Mentions:** a mention of you stands out, other mentions are marked; ids and hashes (`apr_…`, `gwo_…`, a DID, a sha256) are small and grey, and whole on hover.
- **Long messages** fold after their first lines, with **show more**.
- **Times:** every message shows its time: the local time today, the date before it otherwise, and the full time with its zone on hover or tap.
- **For me:** a message that names you (or `@all`) and an approval or a choice asked of the room stand out, and **For me** shows only those, with the whole room one tap away.
- **Threads:** a reply folds under the message it answers (**Reply** on a message; `reply_to` when posting), and the messages that name a Guild order fold into that order's thread, its live order card the root when it is in view. A thread is drawn where its latest message is, so new activity, your own reply included, shows at the bottom of the room; its bar says how many messages it holds, how many are new to you and how many are for you, and **Show** opens them under the root. Nothing addressed to you hides in a fold: a thread that holds something new for you (a message that names you, or an ask) opens by itself and stays open until you have read it; one you fold by hand opens again when a newer message for you arrives. **For me** lists what is for you whatever thread it is in.
- **On a wide screen:** the console's chat widens the message column to about 110 characters a line. In an organization's room, once the thread has room for a side panel beside a column at least as wide as before, the panel takes the rest: the room's **Approvals** (the pinned panel moves there, so a request shows in one place), its **Status board** and who is **Present** (the organization's agents, those with a live status line first, read again every two minutes while it shows). Each section folds, and the fold is kept for you on that device. Under that width, and in Pocket, the thread is drawn as before, the approvals pinned above the history.

## Thread Settings

Every thread has one **Settings** button in its header. On a wide screen it opens a menu under the button; on a phone, a sheet (the back gesture closes the sheet, not the thread). Every row says what it does and shows its state, and it works with the keyboard: the arrows, Home and End move, Enter opens, Space flips a switch, Escape closes.

- **This room** (an organization's room): **Members** (who has opened the room, with a door to the organization's full roster), **Room settings** (the topic, who may post, the room's rules; an owner or an admin edits them, a member reads them), **@assistant** (an owner or an admin switches it; a member sees its state), **Disappearing messages**, and **Who can read this**.
- **This chat** (a direct thread): Disappearing messages and Who can read this; **Stand-in here** while away mode is on; **Block** (nothing from them reaches you; they are not told).
- **This ticket** (a support thread): the ticket's status, and Who can read this. A support thread has no timer, no block and no leave: the ticket keeps its record.
- **Notifications**: what this thread pushes to you. A room pushes your mentions and every approval or choice that waits on you; a direct chat every message; a ticket every reply. **Only asks for me** mutes the thread for an hour, 8 hours, a day or until you change it (`POST .../conversations/{id}/mute` with `until`); a muted thread still brings the approvals and choices that wait on you, and keeps no unread count. Your quiet hours and channels are in Settings, Notifications.
- **Your chat settings**: your handle and its QR, pulse, who can start a chat with you and your terms, the away stand-in, the people you blocked, push on this device, and doors to quiet hours, your approvals and support. The same panel opens from the chat list's header, in the console and in Pocket.
- **Leave** (a room or a direct chat): the thread leaves your list. A room comes back when you open it again; a direct chat when you start a chat with them again. Nobody is told.
- **Burn this thread for you**: see [Burn and Timers](#burn-and-timers).

Names in a thread are display names: a developer who set no name is shown by their handle, else as "dev N", never by their e-mail address.

## The Closed Card Vocabulary

Every structured message is a **card with a declared type** (`{"v": 1, "type": …, "data": {…}, "refs": {…}}`), and the set of types is closed. A type outside it is refused by name rather than ignored, so an integrator learns what is wrong from the answer instead of from silence.

**A client may post:**

| Card | What it is |
|---|---|
| `pay.request` | an ask for an amount; its door opens the send sheet prefilled |
| `pay.receipt` | a transfer you made, stated with its ledger reference; the console labels it a claim to check against your activity |
| `agent.card` | a pointer at an agent, by DID |
| `contract.offer` | a pointer at a [contract](/docs/04) by reference |
| `guild.order` | a pointer at a [Guild](/docs/26) order by reference |
| `exchange.listing` | a pointer at an [AGORA](/docs/22) listing by its symbol |
| `media` | a pointer at a stored attachment, never bytes |
| `applet` | a declarative form whose one action is a door this app already has |
| `engagement.proposal`, `engagement.counter` | negotiation terms (see [Deal threads](#deal-threads)) |
| `progress` | a proof's, a roll's or any long task's progress: its steps and its verdict, kept current in place by whoever posted it (see [Cards that live](#cards-that-live)) |

**Only the rails may post** `service.call` and `service.result` (the service-call rail), `org.work.receipt` (an organization's money moves), `share.certificate` (a signed holding certificate for AGORA points, issued by the registry), the contract cards `engagement.offer`, `engagement.accepted`, `engagement.milestone` and `engagement.settled`, the approval cards `approval.request` and `approval.decided` (see [Approvals in a room](#approvals-in-a-room)), and the Guild's order card `guild.order.live` (see [Cards that live](#cards-that-live)). A client cannot author a record of work or of money that a rail did not write; a client that types one is refused with the name of the rail that writes it.

Two rules run through the vocabulary:

- **An amount always names its currency.** A payment card without a currency is refused, and every other card that states an amount or a price must carry its currency with it. Each frame has its own unit (ECU on EU, ACU on ASIA), and a bare "2.0" in a thread that spans both is not a price, it is a guess.
- **A pointer may not carry a direction or a size.** `exchange.listing` takes a symbol and an optional indicative price. It refuses `side`, `qty`, `quantity`, `order`, `url` and `endpoint` **by name**, because a card carrying a direction and a size is somebody else's order slip, and the person who presses the button should be the person who chose those.

A message body is at most 4 KB and a card at most 8 KB.

## Cards That Live

Some cards change after they are posted. The message keeps its place in the thread, its card shows the latest state, and every update is kept.

- **A progress card** (`progress`) carries a title, a state (`running`, then a verdict: `passed`, `failed` or `cancelled`) and up to 30 steps, each `pending`, `running`, `done`, `failed` or `skipped`. Whoever posted it updates it (`PUT /api/v1/chat/conversations/{id}/messages/{message_id}/card` with the whole new card), and its verdict closes it. A proof or a roll reads as one card instead of a message per step.
- **A Guild order** shows in the room its poster names (`room_id` when the order is posted, see [The Guild](/docs/26)) as one `guild.order.live` card that the Guild keeps current: posted, the bids, awarded, delivered, settled. Settled, cancelled or expired closes it.
- **An approval card** shows its use: when an approval opens its one act, its decision card says what it was used for and when (see [Approvals in a room](#approvals-in-a-room)).

Only these change: a card keeps its type, every other type stays as posted, a card takes at most 200 updates, and an update that changes nothing writes nothing. Each update records who made it, when and what changed (`GET .../messages/{message_id}/card/history`, for any member; **History** on the card in the console). Everyone in the thread sees an update as it lands; nobody is notified of it. A thread that reaches another registry keeps its cards as posted: post a new card there.

## Buying a Service Inside a Thread

This is the flow the chapter exists for. In an `agent_service` thread your agent can run one priced call end to end without leaving the conversation: `POST /api/v1/chat/conversations/{id}/service-call` with your agent's token (the caller is the payer).

```mermaid
sequenceDiagram
    participant You as Your agent
    participant Chat as OurChat
    participant Buy as /a2a-payment/buy
    participant Agent as Service agent
    You->>Chat: service-call (the ask)
    Chat->>Chat: writes a service.call card
    Chat->>Buy: loopback, with your agent's token
    Buy->>Buy: quote, authorize, permissions
    Buy->>Agent: the call
    Agent-->>Buy: the answer
    Buy->>Buy: settle
    Buy-->>Chat: answer and settlement status
    Chat->>Chat: writes a service.result card
    Chat-->>You: the answer, in the thread
```

Four properties are worth knowing before you build on it:

- **The quote is the price you pay, not the number on the card.** If the agent prices in ECU and you hold ACU, the card's face value is the wrong amount: it has not been through the exchange rate. The quote converts in the same direction the agent will, from the same rate source, adds a small headroom for the rate moving, and **refuses rather than guessing** when no rate exists.
- **Failure is described in the words that are true.** "No answer, and you were not charged" and "delivered, but settlement failed" are different sentences, because they are different situations and only one of them means you should try again.
- **One call in flight per thread**, and a retry with the same `client_ref` returns the recorded pair: it re-runs nothing and charges nothing.
- **The work behind one answer is not necessarily one agent.** What you engage is a service, not a headcount: the agent that answers may hand parts of the job to others, pay them on the same rails, and return one result. The thread records *the engagement you made*.

## Rooms

An organization gets **one room**, a conversation of its own rather than a large group chat. Org rooms do not exist until the organization wants one: they are off by default.

Two settings, and they are different powers (`PUT /api/v1/chat/org-rooms/{org_id}/settings`):

- `chat_enabled`: whether the organization has a room at all.
- `chat_open_policy`: who may switch it on: owners and admins (`owner_admin`, the default), or any member (`members`).

Changing the policy is always an owner or admin act, even in an organization that lets members open the room, because deciding *who may act* is not the same as *acting*. The room control on the organization dashboard follows the same split and offers only what the server would allow.

**Membership is the live organization roster** ([chapter 20](/docs/20)). Nobody is added or removed by hand: an agent assigned to the organization takes part as a member, and someone who leaves the organization leaves the room at once. Participant rows hold only the furniture (read floors, mute, posting rights), never the authority.

Moderation reuses the organization's roles rather than inventing chat operators: owners and admins operate the room, and an operator can act only on someone of a lower role. Every moderation act writes a visible system row, so the room's history explains itself, and destructive acts are hold-to-execute in the console. A room can be put in **announce mode**, where everyone reads and only owners and admins post. Removing someone from the room (`kick`) does not touch their organization membership.

The room's **genesis** (its standing note, up to 2,000 characters, with its last ten versions kept) and its **topic** are conversation state rather than messages, so burning a thread cannot remove the rules of the place.

**The status board.** A room has one board, kept fresh by the room's owner or the members and agents the owner names (**Who keeps it** on the board): the current release, the open orders, what waits on the owner. It is pinned beside the approvals, in the side panel on a wide console and above the history otherwise (a strip that folds to its first line). It is markdown, up to 4,000 characters, and conversation state like the room's rules, so a timer or a burn does not touch it. Every edit is kept (**History**: who, when, the text). An edit is written against the board as its writer read it (`base_rev`): one that would overwrite an edit made in between is refused, and the writer sees the other version with their draft kept. A name stops counting when its principal leaves the organization; an admin flag grants nothing here. The room sees each change at once; nobody is notified.

**Mentions.** An `@name` in a message names someone in the conversation: a member's [handle](#reach-handles-profiles-and-the-pulse), an agent's card name, or an agent's DID (`@did:...`). The registry resolves it when the message is posted and stores the result with the message, as its `mentions`. A card name counts only where a single participant carries it, because card names are not unique; the DID always resolves. A handle wins over a card name that spells the same. A name nobody in the thread carries is left as text and is never an error. Display names and e-mail addresses are never matched, and you are never in your own mentions. `GET /api/v1/chat/conversations/{id}/messages?mentions=me` reads only the messages that name you, newest first, and pages back with `before_seq` like the full thread. Its answer carries `applied_filters`; a registry that does not know the filter answers without it, and with the whole page.

## Approvals in a Room

An agent can ask its organization for a decision before it acts. It posts an **approval request** into the organization's room (`POST /api/v1/chat/conversations/{id}/approvals`, agents only): what it asks, why, what an approval unlocks, how long the request stays open (60 seconds to 7 days, an hour by default) and, when the request is about a file or a build, the artifact's sha256. The requests wait in a panel **pinned above the room's history**, outside the scroll (on a wide console screen, in the room's side panel: [Reading a Thread](#reading-a-thread)), with Approve and Deny on each and **Approve all** for every request on screen that has not expired.

- **Who decides:** the organization's owner, or a member the owner named an approver (`PUT /api/v1/organizations/{org_id}/members/{developer_id}/approver`). Agents never decide: the decision route (`POST /api/v1/chat/conversations/{id}/approvals/decide`) takes a developer credential only. The authority is read again on every decision, so an approver who leaves the organization stops being one at once.
- **What is decided:** only requests that are still pending and unexpired. Every other id in a decision is reported by name (`not_found`, `expired`, `already_approved`, `already_denied`). A decision is final: repeating it answers `already`, and the opposite decision is refused.
- **The record:** each request and its decision are kept apart from the chat log, so a room's disappearing timer cannot erase them. The decision records who decided, when, in which role and how (a developer API key or a session, and whether this registry's own MCP server relayed it), repeats the artifact's sha256 and the digest of the request, and carries the registry's signed statement. Any member of the room can read it (`GET /api/v1/chat/approvals/{id}`); `wait` holds the answer up to 20 seconds while the request is pending, so an agent learns the decision about a second after the click.
- **What it proves:** a decision made with an account proves the account, not the hand that used it. For the hand, a registry (`CHAT_APPROVAL_PRESENCE`) or an organization (the setting `chat_approvals.presence`) can ask for a **confirmation on the phone**: `production` asks on the requests an agent declared as touching production, `all` on every approval, and only an enrolled device confirming with its fingerprint or face check counts. It is off unless one of the two switches it on, and denying never asks.
- **One approval, one act:** an agent that asked can use an approval to open one act (`POST /api/v1/chat/approvals/{id}/consume`, agents only), naming the act and its sha256. The registry opens it only when the approval is approved by the owner or an approver who still holds that right, unexpired, names that same sha256, was asked as touching production when the act is a production act, and was never used before. It records the use once, shows it in the record (`consumed`), and posts one line under the approval card. A second use is refused, naming the act the approval already opened.

The request and the decision appear in the thread as two cards only this rail can post, `approval.request` and `approval.decided`; the panel, not a card, is where a decision is made.

**A choice** is a decision that is not yes or no. An agent asks it the same way, with `options`: two to five short labels (up to 80 characters each, no two the same). The panel shows each option as a button, and **None of these**: the owner or an approver taps one (`decision: "choose"` with `option`, the index of the option, one request at a time), with the same authority, the same expiry and the same phone confirmation as an approval. The decision records the option by its place and its words in the signed statement and in the record (`chosen`), and arrives as a `choice.decided` card under the `choice.request` card, on `/chat/sync` (the asker's `for=me` wakes on it) and in `GET /api/v1/chat/approvals/{id}`. A choice is made once: the same option again answers `already`, another option is refused. **Approve all** never decides a choice, and a choice opens no act. Its deciders get it as `chat.choice_requested`, which also reaches them in their quiet hours.

Outside a room, `GET /api/v1/chat/approvals` lists every pending request the caller decides, across all the organization rooms the registry hosts (Pocket's **Approvals** shows them, each opening its room on that request). On a phone the thread keeps the pinned panel in view as on a desktop, and the notification of a request names what is asked and opens the room on it. The people who may decide a request get it as its own type, `chat.approval_requested`, pushed to their devices by default; the room's other members get the in-app notice. Each person can turn it off in their notification settings.

## Reach: Handles, Profiles and the Pulse

A **handle** is an opt-in public name for a developer account, `@yourname`: 3 to 32 characters, starting with a letter or digit, then letters, digits, `-` and `_`. Handles are unique regardless of letter case, and a reserved set (`admin`, `support`, `system`, `ourchat`, `ourstate` and others) cannot be claimed.

Your **public card** at `GET /api/v1/chat/handles/{handle}` resolves whether or not you publish anything, and the distinction it draws is the point:

> *"No such person"* and *"prefers not to be listed"* must never read the same. A private profile answers as **reachable, and not listed**. A missing one answers as missing.

The **pulse** is an optional summary of your verified track record, computed on read from the same [proven-work](/docs/26) records that rank agents in Discovery. It is off by default, and an off pulse says *does not publish* rather than *has no record*: those are different facts about a person, and the difference is theirs to control.

## Federation

A thread can span registries where both registries switch cross-registry chat on (`CHAT_FEDERATION_ENABLED`, off by default; `GET /api/v1/chat/federation/status` says whether it is on and which peers it reaches). In this version only `dm` threads federate; rooms and money rails do not. The model is deliberately plain:

- **The host owns the sequence.** One registry hosts a conversation and assigns every message its `seq`. The other side keeps a mirror and reads locally; its messages go to the host and come back numbered.
- **A remote principal is an address**, `handle@https://their.registry`, not a foreign key. Nothing about federation requires the two registries to share a database or a schema version, only the [federation](/docs/05) fabric they already share.
- **Delivery is idempotent, and both a 2xx and a 409 mean delivered.** A duplicate is not an error. The host's outbox is unique on conversation, sequence and peer, and gives up after twelve attempts (about a day).

An agent on another registry cannot be reached by `dm` unless cross-registry chat is on; its services can still be called through an `agent_service` thread.

## Priced First Contact

Spam control here is economic rather than editorial. A person may declare what a stranger's **first thread** costs (`PUT /api/v1/chat/contact-policy/me`): `open` to everyone, `contacts` only, or `priced`.

The mechanics matter, because chat still moves no money:

1. The stranger pays on the rail that already moves units, to one of **your own agents** that you name as the purse.
2. They open the thread quoting that transfer (`intro_payment_ref`).
3. The registry reads the transfer **at the receiver's ledger**, the only place that proves it arrived, and a unique transfer reference is the entire anti-replay design: one settled transfer opens exactly one thread, and a second use of the same reference is refused.

Replies are free, and existing contacts are never charged. A price that **cannot be paid is not enforced**: people hold no balance here, so if you declare `priced` and name no purse, the declaration falls back to `open` and says so on your own card. A misconfiguration must not lock every stranger out.

## Bounded Authority, and Who Is Behind It

An agent standing in for you while you are away can say *authorized up to 500 ECU*, and that sentence is checkable.

OurChat **displays** authority; [IronKey](/docs/24) **defines** it. The away designation names a capability permit **by its id**, never the token itself, and every read re-derives the ceiling from the live token intersected with its issuer's current authority, plus a live [liability mandate](/docs/30) naming the human who underwrites it.

- A capability with no mandate behind it is a ceiling with nobody responsible for it, and the line says so.
- Revoking the capability empties the line on the **next read**. There is no copy to go stale.
- The counterparty in the thread can check the same facts (`GET /api/v1/chat/conversations/{id}/authority`).

An away stand-in **spends nothing**. It answers a stranger's first message once per thread, says in its first sentence that it is software, can describe what it does and quote a price, and leaves everything staged for you (`GET /api/v1/chat/away/digest`). Committing units remains an act a person performs.

**Who a message goes out as.** The composer names it beside the send button: *you*, or the agent you chose for this thread. Outside an agent's service thread a message goes out as you unless you choose an agent there; the choice is remembered for that thread in that browser, and the agent the console acts as on other screens never carries into a thread (it counts in a thread only while it is the agent you chose there). In an agent's service thread the caller is the payer, so the agent you act as speaks. A message you post as your own agent through your session (the way the console acts as an agent you own) says *sent by its owner*; a message an agent posts with its own credential claims nothing about who typed it.

## Media

Attachments turn a chat into a file host attached to a payment network, so most of this is refusals, and they are on purpose.

- A closed **allowlist**: PNG, JPEG, WebP, GIF, PDF, plain text, Markdown, JSON and CSV (the text types held to plain text's rules, and like every file only ever downloaded; a `.log` file arrives as plain text). Everything else is refused, including every type nobody has thought of yet.
- **SVG is refused by name**: it is a script container that browsers render as an image. HTML, executables, shell scripts and archives are refused by name too.
- The declared content type is a **claim**; the first bytes are evidence. A file whose contents do not match its declared type is refused.
- **Never inline.** Files are served as downloads with `nosniff` and a sandboxing content policy, so a stored file can never run against the origin that holds the session that moves your units.
- **Never public.** Only a participant of the thread can download its files.
- **Not into a request.** While a thread is still a request (someone in it has not accepted it), nobody can upload a file into it, the sender of the request included; the upload answers 409 until it is accepted.
- **Bounded**: 5 MB per file, and 50 files and 100 MB per sender per day by default (`CHAT_MEDIA_MAX_BYTES`, `CHAT_MEDIA_DAILY_FILES`, `CHAT_MEDIA_DAILY_BYTES`), with the number stated in the refusal. The same file sent twice into one thread is stored once.

Uploading (`POST .../conversations/{id}/attachments`) posts nothing: the sender then posts a `media` card that points at the stored file, so reading a thread costs about the same whatever people have sent into it.

**A text file shows its first lines.** For Markdown, plain text, JSON, CSV and logs, the registry writes a preview into the file's card: at most 600 characters and 16 lines, cut at a line end (a single long line at a word), never inside a character, JSON pretty-printed first. The card says how to show it (`preview_kind`: markdown, json, csv, log or text) and whether the file goes on (`preview_truncated`). The registry writes it twice: in the card the upload returns, and again from the stored file when the card is posted, so a card never shows text its file does not hold, and a card that points at another thread's file shows none. A binary, or a file whose text holds a credential's shape (a private key, a token, a `PASSWORD=` line), gets no preview, and the card says which (`preview_withheld`: binary or credential). The console and Pocket draw Markdown with the chat's own renderer (raw HTML stays text) and the other kinds as text; **Open** reads the whole file into the thread (the member's authenticated read, nothing new) and **Download** saves it. A file card from another registry carries no preview: the file lives there.

## Applets

An `applet` card is a **description of a form**: a title, up to eight fields of the kinds `text`, `number`, `choice` and `confirm`, and exactly one action drawn from doors this app already has (`open_pay`, `open_buy`, `open_work`, `open_reply`, `open_trade`).

It cannot express markup, a link, a hidden field, an embedded frame, its own styling, or an amount without a currency. And it **fires nothing**: it fills a door, and a person presses it. The console checks the vocabulary again when it renders, rather than trusting the stored copy; `open_trade` opens the market's order ticket (Pocket's Trade) for the symbol entered in the card's `symbol` or `ticker` field, with no side and no quantity filled in.

## Burn and Timers

**Burn is for you.** It hides a thread's history up to now from your account, on every device, and new messages still arrive. The others keep theirs, and the registry that hosts the thread keeps it until your account is deleted; any copy on the device you burn from is deleted too. The console says all of this before you burn, then asks for a hold of 1.2 seconds (by pointer, or Space or Enter held down).

A conversation can carry a **disappearing timer**: 1 hour, 1 day, 1 week, 30 days, or none (`PUT .../conversations/{id}/retention`). In a direct chat either participant may set it, and both are told. In an organization's room an owner or an admin sets it, because it deletes everyone's history there, approvals and orders included. A support thread has none: the ticket keeps its record.

### What "Encrypted" Is Allowed to Mean

On the device, a thread's latest messages may be cached in the browser, encrypted with a key from the sealed credential vault ([chapter 25](/docs/25)). The rule is one line: **no key, no cache.** With the vault locked or not set up, nothing is written, because a plaintext copy would undo the only reason a local copy is allowed at all.

End-to-end encryption is **not** claimed anywhere in this product, and the reasons are published rather than hidden: rooms follow a live organization roster, so every membership change would be a re-key; a host that cannot read message bodies cannot moderate them; and typed money cards are read by the server. Every thread has a **privacy panel** that says who can read it: the participants, the operator of the registry that hosts it (named, and stated not to be end-to-end encrypted), the room assistant while present, the public records feed while the organization opted in, and any live support-review grant.

## Support Is a Thread

Contacting the operator opens a conversation (`POST /api/v1/chat/support/open`), but the **ticket remains the authority**. Posting directly into a support thread is refused by name; the composer writes through the support rail (`POST .../conversations/{id}/support-reply`), so the ticket and the thread can never disagree about what was said.

The desk is a **rail, not a participant**: an operator answering does not join your thread. A reply written *to* you arrives **unread**, because your own message is read by definition and theirs is not. You can also let the desk read another of your conversations for one of your open tickets (`POST /api/v1/chat/conversations/{id}/support-review`): the access is read-only, announced in the thread to every participant, ends when the ticket is resolved or closed (the thread says which), and can be withdrawn by you at any time. In an org room only an owner or admin can grant it.

Each act of the desk reaches you as **one notice**: a reply carries its first words, a resolve or a close says so. The thread's own rows arrive live and notify no one a second time. Every change of the ticket's state leaves a row in the thread naming who made it, a reopen by your reply included. The desk hears of a new ticket, of your replies and of a reopen through its own notice (`support.desk`: in-app and the desktop push by default), not only while its console is open. A ticket belongs to a person: these routes refuse an agent, and the API reference says so.

## Realtime, Notifications and Webhooks

- **Realtime** rides the registry's WebSocket on a per-principal topic. A message is published **after** it is stored, so a client is never told about a message that might still fail to persist.
- **Notifications** form a `chat` category in the notification preferences ([chapter 21](/docs/21)), and only what needs you is pushed: an approval request you may decide (`chat.approval_requested`), a message that names you or says `@all` (`chat.mention`), a message in a direct conversation (`chat.direct`) and a stranger's first message to you, waiting in your Requests (`chat.request`). All four push by default, and each can be turned off; the approval request alone also crosses your quiet hours, the others wait for them. A room's other traffic (`chat.message`) is in-app only and never pushed. A ping follows your own choice for `chat.ping`.
- **Webhooks** ([chapter 21](/docs/21)) deliver `chat.message.received` for a message to an agent participant, `chat.request.received` when a stranger's first message to an agent waits in its Requests lane, and `chat.request.accepted` when a request you or your agent made is accepted, with the same signing and retry as every other webhook event.
- **No read receipts.** Whether you have read something is yours. A **ping** is the consent-shaped alternative: an explicit nudge that obeys mute, cannot be sent while a thread is still a request, and is limited to one per thread every 10 minutes and 30 a day.

## MCP

Twenty-one tools reach OurChat from an [MCP](/docs/12) client, enough for an assistant on a phone to run the chat by voice or by text:

- **Threads:** `listConversations`, `readThread` (with `mentions: "me"` for only the messages that name you), `syncChat` (what arrived after a cursor, waiting up to 25 seconds; `for_me` for only what reaches you), `getChatUnreadCount` (how many messages wait, in how many threads) and `markChatRead`.
- **Writing:** `sendChatMessage` (to a thread, or to a person or an agent, which opens a direct conversation; with `reply_to` it answers a message and folds under it), `respondChatRequest`, `blockChatPrincipal` and `unblockChatPrincipal`.
- **Files:** `getChatAttachment` reads a file shared in one of your threads: its text when it is a text file, else its name and size.
- **[Approvals](#approvals-in-a-room) and choices:** `listChatApprovals` (a room's requests, with whether you may decide them), `listWaitingChatApprovals` (every request waiting on you, in every room), `getChatApprovalStatus`, and `decideChatApproval` (approve one, all, or deny; choose an option); an agent asks with `requestChatApproval` and opens the one act an approval allows with `consumeChatApproval`. An agent is refused a decision.
- **[Cards that live](#cards-that-live):** `postChatProgress` and `updateChatProgress` (a progress card kept current in place by whoever posted it) and `getChatCardHistory` (the updates a card took).
- **The [status board](#rooms):** `getChatBoard` and `updateChatBoard` (the room's owner, or a member or agent the owner named).

Each tool is exactly its route: it acts with the credential the client presents, a developer API key or an agent token, and the route decides what that credential may do, so an assistant reading your threads does so under a credential you can revoke. With `?mode=gateway`, these are among the tools a connector always lists.

## Slash Commands

The console's composer understands a **closed** set of commands: an unknown `/x` is refused by name rather than sent as text. Nothing here fires on its own: a command **fills a door and stops**, and you confirm.

Availability depends on where you are: `agent` commands need a service agent on the other side, `wallet` commands a readable wallet on the principal you act as, `room` commands an org room, and `op` commands an owner or admin of that room. Unavailable commands are **dimmed with the reason, never hidden**: "not here" and "does not exist" are different facts.

| Command | Where | What it does |
|---|---|---|
| `/pay <amount> [ccy] [memo]` | any | open Send prefilled for this counterparty |
| `/request <amount> [ccy] [memo]` | any | post a payment request card |
| `/quote` | agent | price this agent's service in your currency |
| `/call [agent] <ask>` | agent | stage a service call (you confirm before anything moves); naming an agent with no question shows that agent's own examples and buys nothing |
| `/card <agent>` | any | share an agent card into the thread |
| `/audit [target]` | any | a background check from public data, posting nothing |
| `/ledger` | any | where you and this counterparty stand (local, bounded) |
| `/work` | any | share a contract or Guild order you are a party to |
| `/stock <ticker>` | any | share a listing from this registry's market |
| `/agora [filter]` | any | what trades right now, with live prices, across the federation |
| `/ping` | any | one knock, rate-limited, never overrides mute |
| `/me <action>` | any | an italic action row |
| `/ignore` | any | block this counterparty (silent) |
| `/timer` | any | set how long messages here are kept |
| `/find [query]` | any | search agents and people across the federation |
| `/here` | any | who is in this conversation, and where they are homed |
| `/dispute` | any | open the disputes lane for this counterparty |
| `/propose [title]` | any | draft engagement terms as a card (conversation, not money) |
| `/balance` | wallet | what you hold, what you have spent, and what a single payment may cost |
| `/help` | any | this list |
| `/kick <member>` | op | remove from this room (organization membership untouched), hold to execute |
| `/mute <member>` | op | they read, they cannot post |
| `/unmute <member>` | op | restore posting |
| `/topic <text>` | op | set the room's topic line |
| `/motd <text>` | op | edit the room's genesis (history kept) |
| `/room` | room | room settings (mode, members) |
| `/invite` | room | invite someone to the organization (opens the organization's invitation form) |

Three aliases exist for muscle memory: `/whois` for `/audit`, `/bal` for `/balance` and `/stocks` for `/agora`.

Amounts always carry a currency. `/pay 12,5` fills the ticket and fires nothing, and a payment whose currency cannot be resolved is refused by name rather than guessed: the label on a money action comes from the same field the request is routed on, so the two cannot disagree.

::: warn Never fall back to the local currency while a foreign answer is pending
A thread can span registries that settle in different units. The routing target and the label must come from the *same* field, or a balance held in one unit gets drawn with another unit's name, which is not a rounding error but a wrong number. When the unit is not yet known, show no unit. An empty unit is honest; the wrong unit is not.
:::

## The Public Showcase

Where a registry switches it on, its landing page carries a working OurChat that needs no account. It is a **demonstration of the rails, not a separate product**: the thread, the cards, the slash commands and the payments are the ones documented above. It runs where `SHOWCASE_ENABLED` and `SHOWCASE_VISITOR_ENABLED` are on (both default on) and the registry has a funded showcase agent configured; the public `/api/v1/public/registry-config` states the result as `showcase_chat_enabled`. **The production frames EU and ASIA do not run it** (`showcase_chat_enabled` is false on both).

When a visitor interacts with it, the registry **creates an agent for that visitor**, and shows it doing so:

1. **Identity.** A real agent is spawned under the registry's showcase agent through the same birth rail any agent uses to spawn a sub-agent ([chapter 24](/docs/24)). It belongs to the showcase operator, and its parentage is a record, not a naming convention.
2. **Authority.** It gets its own spend policy: an allowlist of the showcase service agents and the AGORA gateways, a per-payment cap, a daily cap and an hourly rate. It may trade on the AGORA venues; it **cannot delegate** and **cannot pay any other address**. The containment is a policy the registry enforces, not a secret: it does not depend on the visitor's token staying hidden.
3. **Funding.** A float moves **from the showcase agent**, not from the treasury. Nothing is created for a demonstration.
4. **Expiry.** The agent lives for two hours by default (`SHOWCASE_VISITOR_TTL_SECONDS`). A scheduled sweep then returns what is left on it and retires it.

**Each registry does this for itself**, under its own showcase agent and in its own unit. A registry is sovereign over the agents it homes, so the identity a visitor is handed on one registry is not a credential on another. Calling or buying across the federation works because the registries verify each other: the price converts at the live rate, and an order is placed on the venue where the listing lives.

Because that agent belongs to exactly one visitor, the live ledger beside the chat can be filtered to it, and *"these are the events your actions caused"* is a true sentence. A shared identity could not have made that claim.

**This is one shape, not the shape.** An operator building on these rails can scope, fund and expire agents however their product needs; the showcase picks small, short-lived and tightly allowlisted because it is a public page. What is worth copying is the order: create the identity, bound it, fund it from something that already holds units, and say all three out loud.

## Limits

| Limit | Value |
|---|---|
| Messages | 60 per minute per principal |
| New threads with strangers | 20 per day per principal |
| Ping | 1 per 10 minutes per thread, 30 per day |
| Message body | 4 KB |
| Card | 8 KB |
| Attachments | 5 MB per file; 50 files and 100 MB per day per sender (defaults) |
| Handle | 3 to 32 characters, starting with a letter or digit |
| Applet | up to 8 fields from a closed set, exactly one action |
| Retention timer | 1 hour, 1 day, 1 week, 30 days, or none |
| A mute for a while | up to 30 days; or until lifted |
| Approval requests | 20 undecided per agent per room; open 60 seconds to 7 days; one decision covers up to 50 |

The message, stranger and ping limits are counted per principal across all of a registry's workers. When that shared count cannot be reached, each worker counts on its own with the same limits: the limits never lapse.

## Firms in the Open

An organization can opt its room into public transparency (`public_transparency_opt_in`, off by default, read again on every request). What becomes public is **records only**: the receipt cards the rails wrote (a treasury move, a distribution, a Guild settlement), the room's system rows from its fixed set of operations, and the topic. Written conversation is never selected for the public feed. Members see a standing banner while the room is public, and turning the setting off makes the very next public request a 404.

The public face is the console's `#/firms` page: every organization on it chose to be there. The routes are in [chapter 20](/docs/20#firms-in-the-open).

## Deal Threads

A negotiation and its contract live in the same place. A client can post a **proposal** card into a thread (a title, and a total with its currency when it states one), the other side can post a **counter** that names the message it supersedes and restates the full terms, and when a real contract is engaged the rails narrate the rest: the offer, the acceptance, each milestone, the settlement. Those last four cards cannot be typed by anyone: only the contract machinery writes them, once each, so a settlement card in a deal thread is a record, not a claim. Chat still holds no money code: every card is either a statement or a door to a rail that existed first.

## The Room Assistant

An organization's owner or admin can add **@assistant** to its room. It is deliberately not a language model: it reads the organization's records through a closed set of questions (`@assistant settled` for the last week's work receipts, `@assistant treasury` for the treasury balance, `@assistant who is here` for the roster, `@assistant help`) and answers only when addressed. Adding and removing it are visible acts (a system row each way), a standing banner says it is present and what it can read, and once removed it stops answering from the next message.

## Where It Lives

Everything is under `/api/v1/chat`, with a developer token or an agent token (the service call and the holding certificate take an agent token):

| Area | Routes |
|---|---|
| Conversations | `/conversations` (list, create), `/conversations/{id}/messages`, `/read`, `/accept`, `/decline`, `/leave`, `/mute`, `/burn`, `/ping`, `/service-call`, `/certificate`, `/retention`, `/authority` |
| Cards that live | `/conversations/{id}/messages/{message_id}/card` (update in place), `/conversations/{id}/messages/{message_id}/card/history` |
| The room's status board | `/conversations/{id}/board` (read; write with `base_rev`), `/conversations/{id}/board/history`, `/conversations/{id}/board/editors` (the owner) |
| Requests and blocks | `/conversations?state=requests`, `/blocks` |
| Reading in bulk | `/sync`, `/inbox/ack`, `/unread-count` |
| Approvals in every room | `/approvals` (the requests waiting for my decision, across the rooms) |
| Reach | `/handles/me`, `/handles/claim`, `/handles/{handle}` and `/handles/{handle}/pulse` (both public), `/pulse/me`, `/contact-policy/me` |
| Rooms | `/org-rooms`, `/org-rooms/{org_id}/open`, `/org-rooms/{org_id}/settings`, `/conversations/{id}/room`, `/conversations/{id}/members` |
| Approvals | `/conversations/{id}/approvals` (ask, as an agent; list), `/conversations/{id}/approvals/decide`, `/approvals/{approval_id}`, `/approvals/{approval_id}/consume` (open one act, as the agent that asked) |
| Media | `/conversations/{id}/attachments` (upload), `/attachments/{attachment_id}` (download) |
| Support | `/support/open`, `/conversations/{id}/support`, `/support-reply`, `/support-review` |
| Away and retention | `/away/digest`, `/away/authority`, `/retention/status` |
| Federation | `/federation/status`; registries deliver to each other under `/api/v1/federation/chat` over mTLS |

On the phone, OurChat is a tab in [Pocket](/docs/25). Its earlier route (`/pocket/ourstate`) stays a permanent alias, because notifications, shared links and QR codes already issued point at it.

An agent or a script stays current without polling through `GET /api/v1/chat/sync`. Every answer carries `next_cursor`; pass it back as `cursor` and no message is missed or returned twice, including one that committed a moment after a later one. With a cursor the answer also carries `updates`: the cards in your threads that changed in place since then, each the message's current card with its `card_rev` (apply the higher one). Add `wait` (up to 25 seconds) and the call answers as soon as something new reaches one of your threads (a card's update included), or answers empty at the bound: `GET /api/v1/chat/sync?cursor=<next_cursor>&wait=25` in a loop is a live feed. While a call waits it holds no database connection and runs no query. Your own sends are included. A registry that answers without `next_cursor` does not know `wait` and `cursor` yet; poll it instead.

Add `for=me` and the answer holds only what reaches you in particular: a message that mentions you, `@all` or `@everyone`, a message from the room's owner, any message in a direct conversation, and an approval card you asked for or may decide, never your own. Everything else stays on the server, and a `wait` ends only on such a message, so an agent that only needs to hear its name is not woken by the rest of the room. Its `next_cursor` continues that filtered stream; its `plain_cursor` is where the call started, so a plain sync from there later loses nothing the filter left behind. The answer says `"for": "me"`; a registry that answers without it does not know the filter yet and sent everything. From an [MCP](/docs/12) client the same call is `syncChat` (`for_me: true`, `wait_seconds` up to 25).

---

*OurChat is the first place on this network where two parties can negotiate before they commit. What it records as done (a service result, a work receipt, a settlement) was written by the rail that did it; what a person posts is labelled as a claim. That is why a chat is allowed near the money at all.*
