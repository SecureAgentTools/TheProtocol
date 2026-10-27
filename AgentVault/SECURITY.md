# Security

TheProtocol is financial infrastructure: agent identity, a token ledger and a cross-registry settlement
network. Security reports are welcome and taken seriously.

## Reporting a vulnerability

**Do not open a public issue for a security vulnerability.** Email **SecurityAlerts@theprotocol.cloud**;
the same address is published at `https://theprotocol.cloud/.well-known/security.txt` (RFC 9116). You may
report anonymously. Include:

- what you found, where, and what you think the impact is
- the steps to reproduce it (a proof of concept if you have one)
- the affected component and version (registry, TEG layer, event store, directory, auditor, SDK, frontend, kit)
- any suggested remediation

We acknowledge within 24 hours, give a first assessment within 7 days, and aim for a fix or a mitigation
within 30 days, telling you where we stand on the way. If you want to encrypt your report, ask for a key in
a first, unencrypted message. Credit is offered in the advisory if you want it. There is no reward programme
during the beta; we say so rather than imply one.

Research that stays within the Vulnerability Disclosure Policy (`https://theprotocol.cloud/#/legal/security`)
is treated as authorised: no legal action, no complaint, no referral.

## Where to test

Production frames carry real ledgers. Break things in a sandbox: the kit (the quickstart in the public
docs) stands one up in minutes, and the platform's sandbox pair exists for exactly this. A finding shown on
a sandbox is treated as if it were shown in production.

## Rules

No denial of service, no access to other people's data, no value movement beyond dust, no mass creation of
accounts or agents on production, no social engineering of the people who run the platform, and reasonable
time to fix before disclosure.

## Scope

In scope: vulnerabilities in the open-source code of this repository, including

- authentication or authorization bypass (developer JWT, agent JWT, bootstrap tokens, API keys, capability
  tokens)
- ledger integrity (unauthorized issuance, balance manipulation, supply-invariant bypass, double-spend
  across the 2PC and async settlement paths)
- federation and mTLS trust (SPIFFE identity spoofing, card-signature forgery, cross-registry authorization
  escalation)
- cryptographic weaknesses in card signing, event integrity or the identity fabric
- injection, SSRF or remote code execution in the registry, TEG layer, event store, directory or auditor
- escapes from the agent execution and provisioning paths (the frame runner, the operator provisioner)

Out of scope:

- denial of service by raw traffic volume against an instance you control
- vulnerabilities in third-party dependencies already tracked upstream (report them upstream; tell us if a
  fix needs a change on our side)
- issues that need a compromised operator host, physical access or social engineering

Findings against the hosted network at `*.theprotocol.cloud` go to the same address; they are handled as
operational issues under the Vulnerability Disclosure Policy rather than as code advisories.

## Known limitations

They are named here so that nobody has to find them twice; a report is still welcome if it shows a consequence not described
below.

- **One identity for several services, on cloud operator registries.** The architecture audit of 2026-09-25 found frames whose
  registry, TEG layer, event store, mTLS terminators, ledger broker and certificate writer shared one SPIFFE identity, with the
  private key readable by every process on the frame's certificate volume. A frame stood up from the current template
  (`templates/frame-test/docker-compose.frame-test.yml.tmpl`) gets one identity per service, each with its own certificate
  writer, its own key (readable by its owner only) and only the DNS name it serves; the platform's production frames and its
  sandbox pair run this shape since 2026-10-01. The cloud operator registries under a frame are not split yet: an operator's
  services still share one identity.
- **Host reach from the registry, on frames stood up before 2026-09-26.** Such frames mounted the Docker socket and the node
  attestation CA directory into the registry container, so code running as that registry reached the host as root. The frame
  runner's operator socket, a fixed set of narrow operations the registry calls instead, replaces both; the platform's
  production frames hold neither since 2026-10-01, and a frame stood up from the current template never mounts them.
- **Two checks run in shadow on the platform's production frames.** The TEG layer's ledger gate (it refuses a money movement
  while the outbox to the event ledger is unhealthy) and the OPA policy layer count there what they would refuse and refuse
  nothing; the registry's own checks stay authoritative. Both are switches (`TEG_LEDGER_GATE_MODE`, `OPA_ENFORCE`); the
  platform's sandbox runs the ledger gate in enforce.
- **The federation licence gates registry calls only.** The licence certificate gates calls between registries of different
  trust domains; the TEG-to-TEG legs of a cross-frame transfer are not licence-gated yet (they run over mTLS between the
  federated trust domains).
- **A cross-registry delegation revoke is sent once.** Revoking a delegation issued to an agent on another registry ships the
  revocation to that registry once. The issuer sees whether it landed, but a failed shipment is not retried and raises no
  alert, so the far registry keeps honouring the credential until the revocation is sent again or the credential expires.

## Supported versions

The current release line only: security fixes land on the default branch of <https://github.com/SecureAgentTools/TheProtocol> and in the next kit release.
Registries built from the kit report their version and provenance at `/health` and on their registry card;
a modified build says so there. Operators of self-hosted registries should track the latest release and
rebuild their images from it. There is no long-term-support branch yet.

## If you operate a registry

Your registry's security contact is the one in your own legal notice and your own `security.txt`
(`LEGAL_SECURITY_EMAIL`); the address above reaches the software's author, who handles the software, not
your deployment.
