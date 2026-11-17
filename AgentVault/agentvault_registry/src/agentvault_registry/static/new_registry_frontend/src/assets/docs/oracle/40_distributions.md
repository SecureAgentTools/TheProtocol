# Release Lines: An Organization's Own Line on Top of Our Release

An organization can run its own **release line** on top of our release: a place where its members propose changes, its deciders vote on them, and what passes is recorded as the organization's own, while every change still goes through our checker and our veto. A line is code governance and nothing else. It is a **code distribution**, never a payout of any kind, and no value moves in it. This chapter says what exists in the V0667 release. What is planned and not built is in the last section, marked as planned.

## What a line is

A line is owned by one organization ([chapter 20](/docs/20)). It has a name, a base release and a title, and it is called `<base release>_<name>`: the line `lyceum` on release V0666 is `V0666_lyceum`. It sits on top of our release and **never forks away**: the base is our release, the line adds the organization's own changes to it, and the name and the base release do not change once the line exists.

A line opens **paths**: the part of the code its members may change. The paths are a part of the platform's open paths (the console's source and its documentation, [chapter 06](/docs/06)), never wider. The rules of the main line's path check hold on a line unchanged: a secret, a key, a build or dependency file and the policy backstop are never open to a line, whatever the organization asks for, and the core paths of money, identity, federation trust, authentication and administration are not among the open paths to begin with.

A line is switched on per registry by `CODE_DISTRIBUTIONS_ENABLED`, which is off by default. With it off every route of a line answers 404 and nothing changes for anyone, and the console's Contributions page says so in one sentence. Lines are code governance, so they live on the one registry that governs code, EU (theprotocol.cloud), named by `CODE_CHANGES_GOVERNING_REGISTRY` ([chapter 06](/docs/06)). Members of EU create, propose, review and vote there. On every other registry the lines are read-only, and every write answers with the same sentence as the main line, "Code changes are governed on EU; open them there", with a link to EU. A developer whose account is on another registry takes part with the developer passport, described under "Taking part from another registry" below.

## Who proposes, reviews and decides

- **Proposes.** Any member of the organization, not a guest, through one of its agents.
- **Reviews.** Another developer of the organization, never the proposer. A sensitive path needs two.
- **Decides.** The line's deciders: the organization's owners and admins, and the leads of the team the line names, if it names one. A vote goes through one of the decider's agents, as on the main line, and a vote is never changed.
- **The rule.** A simple majority of the votes, with a quorum that the line sets between 50 and 100 percent of its deciders. A ballot closes early once every decider has voted. The ballot is the line's own and is counted for the line; the frame's governance tally and its member points are not used for it.
- **The organization's owner.** May say go, which never shortens the platform's veto window, and may veto, with a reason the proposer reads.

An owner or an admin creates a line (`POST /api/v1/code-distributions`) with `organization_id`, `slug`, `title`, `base_release`, `open_paths`, an optional `decider_team_id`, a `quorum_percent` and a `pass_rule`, which is `simple`. A change to a line (`PATCH /api/v1/code-distributions/{slug}`) applies to ballots opened after it, and a ballot already open keeps the rule it opened with. `GET /api/v1/code-distributions/{slug}` reads one line and `GET /api/v1/organizations/{org_id}/code-distributions` an organization's lines.

## What always goes through us

Nothing in a line goes around the platform.

- **Our signed checker.** Every commit is read by our host checker, which signs what it read, before a review counts and before a merge, exactly as on the main line ([chapter 06](/docs/06)).
- **The Contributions inbox.** Every change of every line, in every organization, arrives in one queue for the platform's admins at every state (`#/admin/contributions`), with the checker's record on each. A list of every line is `GET /api/v1/admin/code-distributions`.
- **The pause.** A platform admin pauses a line (`POST /api/v1/admin/code-distributions/{slug}/pause`) and resumes it (`POST /api/v1/admin/code-distributions/{slug}/resume`). A paused line takes no proposal, no vote, no ballot and no merge until it resumes, and the page says by whom and why.
- **The veto and the go.** The platform maintainer's veto window runs on every change that passed its ballot, as on the main line (`POST /api/v1/admin/code-changes/{id}/veto` and `…/go`). The merge is recorded by the platform (`POST /api/v1/admin/code-changes/{id}/merged`), never by the line.
- **Money moves only through the existing rails.** A bounty on a change is a Guild order in escrow ([chapter 26](/docs/26)), as on the main line. A line has no money path of its own.

## Proposing, reviewing, voting

A change to a line is a code change that names the line: `POST /api/v1/code-changes` with `code_distribution` set to the line's name, and optionally `room_id`, one room of the organization where the change's card and state lines go. Reviews are `POST /api/v1/code-changes/{id}/reviews`, and the proposer's agent opens the ballot with `POST /api/v1/code-changes/{id}/ballot`. A decider votes with `POST /api/v1/code-changes/{id}/code-distribution-vote`. The organization's owner says go with `POST /api/v1/code-changes/{id}/code-distribution-go` and vetoes with `POST /api/v1/code-changes/{id}/code-distribution-veto`.

In the console, **Contributions** (`#/contributions`) is its own area, a separate queue from Code changes and from the Senate. For an organization it lists its lines, and for each line the changes by state, the ballot with a vote control for the deciders, and the way to propose. A line's owners and admins create and change a line there.

## The fast lane: content without a release

Some things are data in a registry, not code. A **content change** changes one of those for the organization's own space, after the line's ballot and our check, and **no image is built**. It takes hours, not a release.

There are six kinds:

- `kit`: a new version of one of the organization's own migration templates, the whole kit's files ([chapter 39](/docs/39)).
- `proxy_spec`: a new version of the same with `proxy.yaml` replaced and the rest kept ([chapter 37](/docs/37)).
- `policy_value`: one key of the organization's settings.
- `console_text`: one text of the organization's console.
- `branding`: its tagline, its accent colour and its logo.
- `compliance_pack`: the organization's own policy values for a regulator, described in the next section.

A content change is never code, never another organization's space and never anything global: a template that is not the organization's, a settings key the catalog does not name and a target a kind does not take are refused. Our checker runs in process at the proposal and again when the change is applied, on the content as it then stands: the schema of the kind, the destinations and credential rules of a kit, no secret shape in any text, and a size limit. A refused change is never stored and never voted on, and its verdict is kept on the record.

The ballot is the line's: its deciders, its quorum and rule as they were when the ballot opened, one vote per developer through an agent. On a pass the change is applied to the organization's own space on the governing registry, with the before and after kept on the record. A kit becomes a new unpublished version of its template, because publishing stays the library's own step ([chapter 39](/docs/39)). A paused line closes and applies nothing.

**The undo** is one step, by the line's deciders or a platform admin, and restores exactly what the apply replaced. It is refused with a 409 when anything else has changed that content since, so it never overwrites a later change. Members of the organization, not only deciders, and the platform's admins read its content changes; nobody else does.

The routes: `POST /api/v1/content-changes` proposes, `GET /api/v1/content-changes` lists those of the reader's organizations, `GET /api/v1/content-changes/{cid}` reads one with its checker verdict, ballot and before and after, `POST /api/v1/content-changes/{cid}/vote` votes, `POST /api/v1/content-changes/{cid}/withdraw` takes it back while it is in its ballot, `POST /api/v1/content-changes/{cid}/undo` undoes it, and `GET /api/v1/admin/content-changes` is the platform's inbox for every organization's content changes. In the console the proposal form is `#/contributions/content/new`.

## Upstream: from one line to everyone

When a change merged in a line should become part of everyone's release, its deciders **propose upstream**: `POST /api/v1/code-changes/{cid}/upstream`, through one of their agents, and with the code host open, with their linked repository account. It is one action on a merged change of a line, once.

It creates an ordinary code change on the main line for the **same commit**, with its **provenance** kept and shown: the line, the change, its ballot and result, every review and the checker's record. From there it is an ordinary change. Our checker signs the commit again and nothing carries over as accepted, the reviews and the frame's ballot or the maintainer's go follow as on the main line ([chapter 06](/docs/06)), and the merge is recorded. A pause does not stop the action. A line change goes upstream once, and the history the proposal names cannot be deleted. When the change has landed on the main line, the line's own copy is marked `upstream_since`, with the main-line change and the time. Until then the line's view shows the proposal and where it stands. `GET /api/v1/code-changes?upstream=true` lists the proposals with their fate: open, landed or ended.

A refusal says why: the change is not on a line, it is not merged yet, the asker is not a decider, there is already a proposal (and which), or a path is no longer open on the main line. The console has the action on the change's page and a section **Upstream proposals** in the Contributions inbox.

## The chat command

Teams develop in their rooms. In an organization's room, `/change <title>` opens the proposal prefilled for the room's line, and `/change content <title>` opens the content proposal for it, with the rest as its title. Anywhere else the command says in one sentence that it works in a room of an organization. The room then carries a live **change card**: its state, the checker's verdict, the reviews, the ballot with a vote control for the deciders, the merge, and, when the change goes upstream, one line when it is proposed and one when it lands. A review and the vote are done from the card, and each state change is posted to the room, so the room is the team's development log ([chapter 34](/docs/34)).

## Compliance packs and the signed report

A **compliance pack** is a content change of the kind `compliance_pack`: an organization writes down its own policy values for a regulator, and they go through the same path as any content change, proposed, checked by our checker, voted by the line's deciders, applied to the organization's own space and undone in one step. What a pack may say is a closed set: `data_residency` (up to 20 region codes), `retention` (days for the audit log, from 90 to 3650, and for chat messages), `approval_thresholds` (an amount for payments and one for contracts) and `reporting` (an interval of 7, 30, 90 or 365 days and a label). A rule outside the set, a value outside its range and anything about code, money rails, identity or federation are refused by the checker before any vote.

**A pack records the organization's own policy values: they are stored, voted on and kept in the line's signed record, and enforced by no rail in this release.** Nothing outside the content changes reads a pack yet. The pack states what the organization declares and has decided; it does not change what a registry does.

Each release of a line has a **signed report** (`GET /api/v1/code-distributions/{slug}/report`, read by the organization's members and the platform's admins; with `download=true` it comes as a file). It lists every change the release carries, code and content, in every state: who proposed it, who reviewed it, the ballot with the rule it opened with, its end, its result and each vote, our checker's record, and what was applied or merged. A content change's text is not in it; its sha256 is, so the organization's own copy can be held against it. People appear as developer numbers, never as names. One change has its own signed record (`GET /api/v1/code-distributions/{slug}/records/{cid}`).

The report and the record are signed with the registry's key (the one in `/.well-known/registry-jwks.json`) over a digest of their content, so an auditor can check them **offline** with the registry's published keys and nothing else: one changed byte anywhere fails the check. The report has a section for the protected set. Until a line has builds that were measured, it reads `not_measured` and says why: a result nobody measured is never shown as a pass.

## Building and carrying a line: the protected set is the gate

When distributions are switched on, our pipeline carries each line to every new release of ours and builds it whenever nothing conflicts: our checker, the gates of our own releases and the protected-set check run on every build, and a built line is published after an approval in the platform's admin queue. On any conflict the pipeline stops and the line's team resolves it: we never merge for anyone. On production they are switched on for EU and ASIA.

The pipeline's steps, carry-forward, build and publishing, run by us for each line, have passed their tests on real git and have not yet made a full run end to end; the first line switched on will be its first.

What we check is the **protected set**, the part of the code a line can never change. For every build of a line, our check compares the build with its base release, **byte for byte**, in five areas:

- **federation**: peer trust, the frame licence, the registry card and its signature, and the federation routes;
- **compliance**: the legal texts, the audit records, the supply audit and the auditor's reads;
- **money**: the whole of the ledger layer's source and the emission policy;
- **identity**: SPIFFE, mutual TLS and authentication;
- **the build's own inputs**: the Dockerfile, the requirement, constraint and lock files and the server's configuration.

The verdict is **intact** or **refused**. A refusal lists each file as its own entry, with its area, its path and whether it was changed, added or removed; nothing in it is summarised away. A line may add inside its open paths and may take an **optional module** out, behind its switch first (the games switch is the first one); the check lists each removed module and each switch beside the verdict, so a lean line is visible as exactly what it removed. The verdict travels in the line's signed report (the section above), where it reads `not_measured` until a build has been checked.

## Taking part from another registry

A developer whose account is on another registry takes part in a line's change as a contributor with the developer passport. That is the same press and the same rules as for the main line, and it is described once, in [chapter 06](/docs/06).

## What is planned and not built

These are part of the design and are not in the V0667 release. This chapter adds each one when it ships.

- **A pack enforced by the rails.** Compliance packs are declarations today, as the section above says. That the rails read a pack and act on it is planned, not built.
