# Licensing

TheProtocol is **licensed by component**. The split is deliberate: the **server/platform is copyleft** (so it can't be
captured into a closed proprietary service), while the **client SDKs and the independent auditor are permissive** (so
anyone can build agents, integrations and verifiers with no copyleft obligations), and the **documentation and protocol
specifications are open** (so anyone can implement the protocol).

| Component | Directory | License |
|---|---|---|
| Registry (FastAPI backend + Vue frontend) | `AgentVault/agentvault_registry/` | **AGPL-3.0-or-later** |
| TEG Layer (token exchange gateway) | `AgentVault/agentvault_teg_layer_mvp/` | **AGPL-3.0-or-later** |
| Event Store (CQRS ledger) | `agentvault-event-store/` | **AGPL-3.0-or-later** |
| ZKP circuit registry (circuits, policies) | `AgentVault/agentvault_circuit_registry/` | **AGPL-3.0-or-later** |
| Identity Fabric (SPIRE / OPA config) | `identity-fabric/` | **AGPL-3.0-or-later** |
| Federated directory (the cross-frame index) | `directory/` | **AGPL-3.0-or-later** |
| Operator tools, sidecars, web server configuration, scripts, templates | `tools/`, `sidecars/`, `nginx/`, `scripts/`, `templates/` | **AGPL-3.0-or-later** |
| Umbrella / platform | `AgentVault/` | **AGPL-3.0-or-later** |
| The independent auditor | `Agents/TheAuditor/` | **Apache-2.0** |
| Client SDK (Python/JS) | `theprotocol-sdk/` | **Apache-2.0** |
| Agent library | `AgentVault/agentvault_library/` | **Apache-2.0** |
| Server SDK (agent build kit) | `AgentVault/agentvault_server_sdk/` | **Apache-2.0** |
| CLI | `AgentVault/agentvault_cli/` | **Apache-2.0** |
| Public documentation and protocol specifications | `PUBLIC_DOCS/`, the docs chapters under `AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/` | **CC BY 4.0** |

Anything in this repository that the table does not name is licensed under AGPL-3.0-or-later, unless its own directory
carries a different `LICENSE`. [`REUSE.toml`](REUSE.toml) records the same map for every file in the form licence
scanners read (the [REUSE](https://reuse.software) specification), and [`LICENSES/`](LICENSES) holds each licence's
text.

The full AGPL-3.0 text is in [`LICENSE`](LICENSE), exactly as the Free Software Foundation publishes it.
Each component also carries its own `LICENSE` file. Where a directory's `LICENSE` and this table ever
disagree, the directory's `LICENSE` governs.

## Copyright and license notice

The server/platform components (every AGPL-3.0-or-later row above) carry this notice:

```text
TheProtocol — Sovereign Agent Infrastructure
Copyright (C) 2025-2026 Raphael Zbigniew Jeziorny

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
```

## Why this split

- **AGPL-3.0 on the server**: the network-use clause means anyone who runs a modified TheProtocol
  as a service must publish their modifications under the same terms. This forecloses the specific
  capture pattern we want to prevent: a vendor forking the stack, stripping the federation
  protocol, and offering the result as a closed proprietary managed service without contributing
  back. AGPL is OSI-certified open source: you can read, run, modify, self-host, and contribute on
  day one. A deployment names where its source is with one setting, `SOURCE_CODE_URL`, which the console
  shows on its legal pages; an operator who modifies the software points it at their own repository.
- **Apache-2.0 on the client SDKs and the auditor**: building an agent, a client, an integration or an
  independent verifier should carry no copyleft burden, so the things people write *on top of* TheProtocol,
  and the tools that check it, stay theirs.
- **CC BY 4.0 on the documentation and specifications**: a protocol spreads when anyone can implement it from
  its description, quote it and translate it, without touching the server's code.

## History

An early version of this code base (a Python library, a registry API and a command line tool) was published in
April and May 2025 at <https://github.com/SecureAgentTools/AgentVault> and on PyPI (`agentvault`,
`agentvault-cli`, `agentvault-server-sdk`) under the Apache License 2.0. Those releases keep that license.
Everything published after them is licensed as this file describes.

## Contributing

TheProtocol accepts contributions under two documents that ship in this repository: the
**Developer Certificate of Origin 1.1** ([`DCO.md`](DCO.md)), certified by the `Signed-off-by` line
every commit carries (`git commit -s`), and, for code, documentation and other copyrightable material,
the **Contributor License Agreement** ([`CLA.md`](CLA.md)), accepted once per person or organisation.
Inbound = outbound: contributions to the server/platform enter under AGPL-3.0-or-later and SDK
contributions under Apache-2.0, you retain copyright, and the CLA binds the maintainer to keep every
contribution available under an OSI-approved open-source license. The CLA also grants the maintainer
the right to license contributions under separate commercial terms (below) and a patent license for
the contribution. [`CONTRIBUTING.md`](CONTRIBUTING.md) says how to accept it.

## Commercial licensing

AGPL-3.0 is not viable for every organization (some legal/OSS policies disallow AGPL dependencies).
If you need TheProtocol under different terms (for example to embed it in a closed product), a separate
commercial license may be available; licenses are granted case by case. It covers the code whose rights the
maintainer holds and every contribution accepted under the CLA, which grants that relicensing right; a
contribution that came in under the DCO alone is relicensed commercially only with its author's separate consent.
Contact: **Raphael Zbigniew Jeziorny, r.jeziorny@theprotocol.cloud**.

## Trademarks

"TheProtocol", "The Protocol" and the associated logos and trade dress identify this project and the
author's network. Neither code license grants trademark rights (Apache-2.0 § 6 says so; the AGPL grants
none), and nothing in this repository does either. Do not use the names or the logos for a modified version,
a fork or an independent deployment in a way that suggests it comes from, or is endorsed by, the author, or
that it is part of the author's network. Truthful nominative use ("compatible with TheProtocol", "based on
TheProtocol", "participates in TheProtocol federation") is fine. A registry that federates with the network
wears its own name; the Federation Operator Terms on the legal page say what it may say about the network.

## Third-party software

The distribution includes third-party components under their own licenses; [`NOTICE`](NOTICE) lists the ones this
repository carries, and each build of the web application writes the notices of every package it bundles to
`THIRD_PARTY_NOTICES.txt` beside it.

---
*Copyright © 2025-2026 Raphael Zbigniew Jeziorny. See [`LICENSE`](LICENSE) for the AGPL-3.0 grant and warranty
disclaimer.*
