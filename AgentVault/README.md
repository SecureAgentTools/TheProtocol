# AgentVault

**TheProtocol is a sovereign agent infrastructure platform. The server infrastructure is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-or-later); the client SDK and agent libraries are Apache 2.0.**

In a world with increasingly sophisticated and numerous AI agents, the ability for them to discover each other, communicate reliably, and collaborate securely is paramount. AgentVault provides the foundational infrastructure and tooling to make this possible, fostering a more connected and capable AI landscape.

---

**Full documentation: [docs.theprotocol.cloud](https://docs.theprotocol.cloud)**

---

## Contributing

Contributions are welcome: issues and pull requests go to <https://github.com/SecureAgentTools/TheProtocol>.
Every commit carries a Developer Certificate of Origin sign-off, and code
contributions come with a one-time acceptance of the Contributor License Agreement: see `CONTRIBUTING.md`
and `CLA.md` here, and the full guide (`CONTRIBUTING.md`, `DCO.md`, `CLA.md`) at the root of the published
tree, one level up.

## Security

Report vulnerabilities to **SecurityAlerts@theprotocol.cloud** (the address published in
`https://theprotocol.cloud/.well-known/security.txt`), never in a public issue. `SECURITY.md` has the scope
and the response times.

## License

TheProtocol infrastructure (Registry, TEG Layer, Event Store, Identity Fabric) is licensed under the [GNU Affero General Public License v3.0](../LICENSE) (AGPL-3.0-or-later). You may use, modify and distribute it; if you distribute it, or modify it and let people use it over a network, you must offer them the source of your version under the same license.

The **federation license**, the signed certificate that lets an operator's registry peer with a specific network, is separate from the source code license: a registry that runs standalone needs none. It is issued free of charge today: without an end date for private individuals and educational, research and non-profit organisations, and for twelve months, with renewal offered, for enterprises and public authorities. For enterprises and public authorities a fee for later license terms may be introduced; it is planned only to cover the costs of operating the network, not to make a profit, and it is not in place yet. The Federation Operator Terms say when a license can be suspended or revoked.

The client SDK (`theprotocol-sdk`), the agent library (`agentvault_library`), the CLI (`agentvault_cli`) and the server SDK (`agentvault_server_sdk`) remain under Apache License 2.0 for permissive downstream reuse by agent developers. The documentation chapters in the console (`agentvault_registry/.../src/assets/docs/`) and the published documentation are licensed under CC BY 4.0. The names and logos are not licensed with the code; `LICENSING.md` at the root of the published tree says what use of them is fine.

## Legal

The legal set of the public network (Terms of Service, Privacy Policy, Risk Notice, Software License Notice, Vulnerability Disclosure Policy, Federation Operator Terms) is published at https://theprotocol.cloud/#/legal and describes the author's own deployment. A registry you run serves its own legal pages from the provider facts you configure (`LEGAL_*`); `PUBLIC_DOCS/11_LEGAL_FOR_OPERATORS.md` at the root of the published tree walks through it.
