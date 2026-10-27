# Contributing to TheProtocol

This repository (the registry, the TEG layer, the agent library, the server SDK and the CLI) is part of the
TheProtocol tree. Contributions to it follow the contribution guide at the root of the published tree,
`CONTRIBUTING.md`, one level up. Issues and pull requests go to <https://github.com/SecureAgentTools/TheProtocol>. In short:

- a contribution is judged on its substance (the evidence, the design, the change), never on who sends it: names, titles,
  employers and reputations elsewhere earn no credit and cost none;
- every commit carries a Developer Certificate of Origin sign-off (`git commit -s`; `DCO.md` at the root);
- code, documentation and other copyrightable material come with a one-time acceptance of the Contributor
  License Agreement (`CLA.md` here, the same text as at the root): it keeps your copyright with you, keeps
  every contribution available under an open-source license, and lets the maintainer also offer the
  project under commercial terms;
- the registry suite runs in the image (`pytest` under `agentvault_registry/`), the frontend has `vitest`
  and a type ratchet, and CI runs both plus the compile and import gates;
- a change to the platform comes with the evidence that it breaks nothing the release passed: the MCP
  tester in a sandbox, before and after (`PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md` at the root);
- the supply invariant stays at zero: anything that moves value calls the existing transfer rails;
- search the routers before building a capability, because most rails already exist behind a flag;
- no secrets, no personal data of the operator, no em dashes in anything a user reads.

Security issues go to the address in `SECURITY.md`, never to a public issue.
