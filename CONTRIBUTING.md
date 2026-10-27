# Contributing to TheProtocol

Thank you for looking under the hood. This file says how a change gets in, what you agree to when it
does, and where to break things safely first. TheProtocol is open source: the server/platform under
**AGPL-3.0-or-later** and the client SDKs under **Apache-2.0** (see [`LICENSING.md`](LICENSING.md)).
The code base lives at <https://github.com/SecureAgentTools/TheProtocol>: issues and pull requests go there.

## 1. What you agree to

Two documents, both in this repository:

- **Sign off every commit** (required). Every commit carries a `Signed-off-by:` line with your real name
  and an email address you control; `git commit -s` adds it and `git rebase --signoff` fixes existing
  commits. By signing off you certify the **Developer Certificate of Origin 1.1** ([`DCO.md`](DCO.md)):
  you wrote the change or have the right to submit it under the component's license, and you understand
  that the contribution is public and recorded. Commits without the line cannot be merged.
- **Accept the Contributor License Agreement once** (for code, documentation and other copyrightable
  material). [`CLA.md`](CLA.md) keeps your copyright with you, keeps every contribution available under
  an open-source license forever, grants a patent license for what you contribute, and lets the
  maintainer also offer the project under commercial terms, which is what funds it. Accept it with one
  line in your first pull request (the file says how); an organisation accepts once for the people it
  names. A pull request from someone whose acceptance is not on file is held until it is.

Inbound = outbound: your contribution enters under the license of the component it touches
(AGPL-3.0-or-later for the server/platform, Apache-2.0 for the SDKs) and can never become
proprietary-only.

## 2. Before you start

- **Discuss anything larger than a fix first**: open an issue describing the change, so the design is
  agreed before the work is done. A change to money, contracts, identity or federation, and any change over
  the size caps (20 code files or 600 changed lines; 12 or 400 in those four areas), needs that design issue
  agreed first. It is then built on a feature branch the issue names and brings one evidence run for the whole
  branch ([`REVIEWING.md`](REVIEWING.md) §4).
- **Stand up a sandbox.** [Test-verified development](PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md) explains
  the loop: a frame from the kit, the MCP tester as the verdict, a comparison before and after your change.
  Production frames are not test targets; the Vulnerability Disclosure Policy on the legal page says what
  good-faith research is.
- **Search the routers before building a capability**: most rails already exist behind a flag, and "it
  does not work" and "it is switched off" look the same from outside.

## 3. How a change gets in

1. Make the change on a branch, with tests. The registry suite runs in the image (`pytest` under
   `AgentVault/agentvault_registry/`), the frontend has `vitest` and a type ratchet, and CI runs both plus
   the compile and import gates.
2. Keep the pull request focused: one logical change, matching the style, naming and structure of the
   file you are editing (Python on the backend, Vue 3 + Pinia on the frontend).
3. Bring the evidence. A change to the platform comes with proof that it breaks nothing the release
   passed: run the MCP tester's suite in a sandbox, once on the release and once on your build, and attach
   the archive `frame-contribute.py` packs (the patch, both reports and their comparison). A change to the tests
   brings a third run per flow, the control ([test-verified development](PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md) §3b).
4. Sign off every commit, accept the CLA if you have not yet, and open the pull request. Describe what
   changed, how you proved it, and what you could not measure.
5. What happens next is written in [`REVIEWING.md`](REVIEWING.md): the maintainer runs `frame-review.py` over
   your archive and you get its page back, verdict by verdict, then the diff is read. Expect an acknowledgement
   within seven days.

## 4. Rules of the road

- **Substance, not standing.** A contribution is judged on what it is: the evidence it brings, the design it
  follows and what it changes. Who sends it does not enter the decision. Names, titles, employers, followings
  and reputations elsewhere earn no credit and cost none; a first contribution and one from a recognised name
  meet the same bar, and the same holds for issues, reviews and design discussion.
- **The prime invariant.** TheProtocol enforces a zero-tolerance token supply invariant (Δ=0). Anything
  that moves value calls the existing transfer rails and keeps the invariant; such changes get extra
  scrutiny.
- **Secrets never enter the tree**: no keys, passwords, tokens or personal data of the operator in
  source, fixtures, screenshots or locale bundles. The export gates refuse them; so do the reviewers.
- **A gate that cannot fail measures nothing**: a new test needs a control that fails for the right
  reason.
- **Tool-assisted work is yours.** If you used an AI or another automated tool, you remain responsible
  for the contribution and certify it the same way, and you must not submit material the tool reproduced
  from a source whose license does not allow it (CLA § 7). Say so in the pull request when a substantial
  part was generated; reviewers read those parts more slowly.
- No em dashes in anything a user reads. Sentence case. Plain verbs.

## 5. How to run it

Per-component setup lives in each component's `README` and the project `README`. The stack runs under
Docker Compose; the registry, TEG layer and event store each have their own service. Start with the
component you are changing rather than the whole fleet; to see a change run end to end, stand a sandbox
up beside a frame (README, "Test a change before you suggest it").

## 6. Security issues

**Do not file public issues for security vulnerabilities.** Report them to
**SecurityAlerts@theprotocol.cloud** as [`SECURITY.md`](SECURITY.md) describes; the same address is
published in `https://theprotocol.cloud/.well-known/security.txt`.

## 7. Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Be respectful and
constructive; harassment or abuse is not tolerated. Report conduct concerns to
**r.jeziorny@theprotocol.cloud**.

---
*Questions about licensing or a commercial license: **r.jeziorny@theprotocol.cloud**.*
