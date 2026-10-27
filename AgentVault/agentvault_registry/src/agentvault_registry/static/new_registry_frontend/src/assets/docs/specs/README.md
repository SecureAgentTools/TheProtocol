# TheProtocol public specifications

Version 1, 30 September 2026

This specification is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny.

## Conformance

This file is an index and states no requirements of its own. Each specification below defines its own conformance classes and uses the key words MUST, SHOULD and MAY in the sense of RFC 2119.

## Specifications

| Document | Version | What it specifies |
|---|---|---|
| [registry-card-v0.6.md](registry-card-v0.6.md) | 0.6 | The registry card: the Ed25519-signed JSON document every registry serves about itself at `/.well-known/registry-card.json`, its fields, its signed paths, its compliance digest, its entity tag and how peers verify it. |
| [registry-card-v0.6.schema.json](registry-card-v0.6.schema.json) | 0.6 | The JSON Schema (draft 2020-12) for version 0.6 registry cards. |
| [supply-audit-standard-v1.0.md](supply-audit-standard-v1.0.md) | 1.0 (TPSA-1) | The supply attestation standard: the supply invariant an auditor checks for each frame, and the signed, hash-chained attestations that let anyone verify the auditor's verdicts offline. |
| [federation-licence-certificate-v1.md](federation-licence-certificate-v1.md) | 1 | The federation licence: the issuer-signed certificate (genesis, frame, operator) a registry needs to federate across trust domains, its plans, how it is issued, verified and revoked, and how a registry card carries it. |
| [a2a-payment-extension-v1.md](a2a-payment-extension-v1.md) | 1 | The A2A payment extension (`https://theprotocol.cloud/extensions/v1/auth/a2a-payment`): how an agent card declares a price, and the authorize, verify, settle and release protocol between a paying agent, its registry and the paid service. |

## Licence

All documents in this directory are licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny. You may share and adapt them for any purpose, provided you give appropriate credit, link to the licence and indicate if changes were made.
