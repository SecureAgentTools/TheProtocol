<!--
Thank you for the change. CONTRIBUTING.md says how a change gets in, REVIEWING.md what happens next.
Security vulnerabilities never go into a pull request or an issue: SECURITY.md says where they go.
-->

## What changed

<!-- One logical change. Name the component: registry, TEG layer, event store, directory, auditor, SDK, frontend, kit or docs. -->

## How you proved it

<!--
A change to the platform brings the archive frame-contribute.py packs: the MCP tester's suite in a sandbox, once on the
release and once on your build, and their comparison (PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md). A change to the tests
brings the control run as well (section 3b there). Attach the archive or link it.
-->

## What you could not measure

## Checklist

- [ ] Every commit carries a `Signed-off-by:` line with my real name (the DCO 1.1 in `DCO.md`; `git commit -s` adds it).
- [ ] My CLA acceptance is on file, or I add the line from `CLA.md` ("How to accept") under this list.
- [ ] A change to money, contracts, identity or federation, or one over the size caps, has an agreed design issue: #
- [ ] No keys, passwords, tokens or personal data in the source, fixtures, screenshots or locale bundles.
- [ ] Every new test has a control that fails for the right reason.
- [ ] If an AI or another tool generated a substantial part, I name that part here and certify it the same way (CLA section 7).
