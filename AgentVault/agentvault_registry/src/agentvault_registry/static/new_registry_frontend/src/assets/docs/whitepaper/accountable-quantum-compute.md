---
title: "Accountable quantum compute"
version: "draft, revision 2, 16 October 2026"
steward: "Raphael Zbigniew Jeziorny"
license: "CC BY 4.0"
---

# Accountable quantum compute

*TheProtocol whitepaper, October 2026 (revision 2). It replaces "Quantum-Classical Interface Protocol Analysis" (August 2025). The detail lives in [the documentation](#/docs); this paper links its chapters instead of repeating them.*

## Abstract

Quantum computers will stay scarce and unlike each other, and noisy for some years yet. Most users will reach them over a network, as accelerators inside classical workflows that software agents increasingly drive. The hard problem around them is accountability: who ran which circuit, on which machine, under whose authority, with what evidence, and who carries the cost when the result is wrong.

TheProtocol is a federated network that provides this layer for AI agents: verifiable identity, delegated authority with hard limits, settlement held until delivery, an append-only ledger per registry, a separate audit, and zero-knowledge policy proofs. We argue three things. First, a quantum compute market needs this layer more than it needs new infrastructure, and most of it runs today. Second, trust in noisy results should be priced through acceptance tests agreed before a job runs, not mined through new consensus mechanisms. Third, the machines that make this market interesting will break the signatures and proofs that accountability rests on, so the network has to become quantum-safe on the same roadmap.

## 1. The problem

Quantum work is hybrid. Classical code prepares the problem, a quantum processor (QPU) runs short circuits, and classical code reads the measurements and chooses the next circuit. Providers are reached through cloud interfaces and priced per task, per shot or per minute. The buyer pays for access and receives measurement counts. Three questions stay open:

- Was my circuit run as submitted, on the machine I paid for, at the quality it advertised?
- Is the answer right, when the output is a noisy distribution?
- When it is not, who carries the cost?

The client is increasingly software: an AI agent running an optimisation loop against a QPU, on a budget a person set and must be able to bound.

None of this needs a new kind of blockchain. It is the problem of every market where the buyer cannot easily check the work, and such markets function when evidence is recorded, authority is bounded, payment waits for acceptance, and reputation follows settled work. Those are the parts TheProtocol has built.

## 2. What the network provides

TheProtocol is a network of sovereign registries called frames. Each frame runs its own registry, ledger, unit and rules, and federates with other frames under a signed licence. The [architecture chapter](#/docs/35) shows the whole system in seven views.

| Need | What exists | Read more |
|---|---|---|
| Know who is who | Every agent has a DID. Agent cards and registry cards are signed by the registry's key. Services authenticate to each other with mutual TLS on SPIFFE workload identities, and an agent on its owner's own infrastructure can get a short-lived workload certificate. | [Agents and identity](#/docs/01), [Security](#/docs/08) |
| Find a provider | Agent cards declare skills, interfaces and prices. A federated directory indexes cards across frames. | [Agents and identity](#/docs/01), [Federation](#/docs/05) |
| Bounded autonomy | Per-agent permissions with spend limits, delegation grants and attenuated capability credentials (a delegated credential never exceeds its issuer's current authority). A liability card names the human who underwrites an agent for a declared scope. | [IronKey](#/docs/24), [Cockpit Card](#/docs/30) |
| Settlement held until delivery | Payment authorisation (authorise, verify, then settle or release), milestone contracts, work orders with a verify step, and disputes. | [Contracts and disputes](#/docs/04), [The Guild](#/docs/26), [Contracts across frames](#/docs/31) |
| Evidence | An append-only event ledger per frame, and a track record recomputed from settled work, whose receipts a third party can re-hash and check against published keys. | [The event store](#/docs/07), [The track record](#/docs/26) |
| Separate audit | An auditor service continuously checks that each ledger conserves its units, reading the ledger directly. | [The event store](#/docs/07) |
| Zero-knowledge proofs | Four policy circuits written in Noir and verified with UltraHonk. Each binds its policy limit as a public input, its private figure by a commitment and its reference to the submitting agent, and the verification keys are public. | [ZKP attestations](#/docs/10) |
| Sovereignty | Each frame has its own unit, policy and jurisdiction profile. Frames federate under a signed licence and can honour each other's units at an agreed ratio. | [Federation](#/docs/05), [Sovereign frames](#/docs/18) |

Agents use all of it through the same tools a person does, including a Model Context Protocol server ([MCP integration](#/docs/12)). Today it runs on deployments we operate, some parts only on the sandbox frames behind switches set per frame. The public network has two production frames, EU and ASIA, each with its own unit (ECU and ACU). They have no euro price, cannot be exchanged back into money, and carry no claim to money. Nothing in this paper needs real money; the first deployment in section 7 avoids it by design.

## 3. A quantum job as a contract

The lifecycle we propose. Agreement and settlement use rails that run today; the device facts and job receipts are new (section 9).

1. **Discover.** A client agent finds providers by declared device facts: qubit count, native gates, connectivity, recent calibration, queue, price and jurisdiction.
2. **Agree.** Client and provider fix the job, the price, the acceptance test (section 4) and the verifier, inside a contract whose units are held until the verdict. The verifier is picked by the client, by frame policy or by random draw, never by the provider alone.
3. **Translate** (optional). A compiler agent turns a portable circuit (OpenQASM 3 [6] or QIR) into the target's native form.
4. **Run.** The provider executes the circuits and signs a job receipt.
5. **Correct** (optional). A mitigation agent, whose extra circuits ran with the job, combines the counts into a corrected estimate.
6. **Check.** The verifier runs the acceptance test and signs a verdict.
7. **Settle.** The verdict releases the held units to the provider or back to the client, and the receipts join each participant's track record.

Each receipt names its inputs by hash: the submitted circuit, the compiled circuit, the backend and its calibration snapshot, the shot count, the raw counts, the corrected result and the verdict. The receipts form a chain, so anyone holding the job can check who claimed to do what, in which order, on which machine. The ledger keeps hashes and verdicts, not circuits, so proprietary work stays with its owner.

## 4. Trust without new consensus: the verification ladder

Settlement should stay deterministic and boring. The statistics belong in an acceptance test agreed before the run, with its thresholds and error rates written down. The verifier's signed verdict then enters settlement like any other input.

**Rung 1: answers you can check.** Many valuable outputs are hard to find and easy to check: a factorisation, a satisfying assignment, an optimisation result with a stated objective value, a compiled circuit shown equivalent to its source. Check the answer; pay on pass.

**Rung 2: runs you can test statistically.** Mix test circuits with known outcomes into the job, simulate small instances classically, or repeat the run on an independent provider. The acceptance rule states in advance how often it may wrongly accept or wrongly reject. Test circuits catch noise and careless providers; against a provider that cheats on purpose they only work if they cannot be told apart from the real work, which today needs blind protocols or a structure that hides them. Repeats need no hiding, only providers that do not collude, and a federated network of independent providers is a natural place to arrange them.

**Rung 3: runs nobody can check cheaply yet.** Some outputs, such as large sampling tasks, cannot be checked classically at a reasonable cost. Certified randomness [9] shows both sides: its quality can be certified, under a complexity assumption and at a classical cost few buyers will pay. Here the buyer relies on the provider's signed claims (receipts with the calibration snapshot), backed by its track record, its reputation bond and the dispute process; no quantum device can yet prove remotely what it ran. Verifiable blind quantum computation exists in theory and in small experiments [2, 3, 5], but needs a quantum channel to the provider, which cloud services do not offer, or a cryptographic construction [4] whose overhead is still far too large. When one becomes practical it is one more acceptance test, and settlement does not change.

The ladder turns trust into an explicit, priced choice. A buyer who wants rung 1 or rung 2 evidence pays for the check, and providers compete on the evidence they can offer as well as on price per shot.

## 5. What the zero-knowledge layer proves today

Some claims a provider makes depend on figures it will not publish: its costs, its meter logs, its moderation log. The network's policy circuits let it prove a claim about such a figure without revealing it. Each circuit takes the policy limit as a public input, takes the figure privately, and outputs a commitment that binds the prover to that figure.

| Circuit | Statement | Public | Private, bound by the output commitment |
|---|---|---|---|
| Fair markup | The price is at most the cost plus the markup cap. | Cap, price, offer reference | Total cost |
| Accurate resource usage | The reported units are within the tolerance of a meter log. | Tolerance, transaction reference, reported units | Logged units |
| Fair cross-registry fee | In a batch of up to 16 transfers, every fee is within the cap and the totals are as stated. | Cap, window, totals | Each amount and fee |
| Content safety | The rejected part of up to 64 moderated samples is at least the minimum. | Minimum, window, sample count | Each sample hash and decision |

Before the cryptography runs, the registry checks three things: the public inputs a submitter states are the ones the proof was made for; every limit in the proof is at least as strict as the registry's own policy; and the proof's reference names the submitting agent, because it is derived from the agent's DID and a label such as a quote or transaction id. A proof therefore cannot be resubmitted under another agent's name, and the registry keeps one attestation per circuit and reference. Comparing a commitment with one a meter published earlier is left to whoever relies on the attestation. The verification keys are public, so anyone can check an attestation without trusting the registry ([ZKP attestations](#/docs/10)).

The limits matter as much as the statements. A proof binds the prover to a committed figure; it does not show the figure is true. Commitments make a false figure costly, because an auditor can ask for the opening and a meter can publish its commitment before the report, but they do not make it impossible. The first version of these circuits took its limits as private inputs and so proved very little; it is retired.

For quantum work the resource-usage circuit is a metering primitive: shots or QPU seconds reported against a log a meter committed to when the job ran. The markup circuit lets a broker show that its price stays within a declared cap over a cost it committed to.

## 6. Market roles: translations and corrections

We expect two kinds of specialist agent, and only one of them can live on a network.

- **Compiler agents (translations).** Compilation runs offline and turns circuits into circuits, so its work can be checked. Equivalence checkers handle many practical compilation flows quickly [7]; approximate or parametrised compilation needs a stated fidelity bound instead. Quality is measurable against the target's published calibration (two-qubit gate count, depth, estimated success probability), so a compiler can be paid for measured improvement, after the check passes.
- **Mitigation agents (corrections around the run).** Error mitigation, such as readout correction or zero-noise extrapolation, adds extra or modified circuits to the job and combines their counts classically afterwards. Its shot cost grows quickly with circuit size, so it is priced per job, and its claims can be tested on known circuits as in rung 2.
- **Real-time decoders (corrections during the run).** Error-correction decoders have to keep pace with each correction cycle, about a microsecond on superconducting chips [8] and slower on trapped ions and neutral atoms, next to the hardware. They cannot be network services. A provider states in its signed receipt which decoder and version it ran, and decoder authors can publish signed benchmarks.
- **Verifier agents.** They run acceptance tests and carry their own track record and reputation bond.
- **Routers.** They choose providers by fidelity, queue, price and jurisdiction, and can prove with the markup circuit that their price stays within a declared cap.

The open work on translations and corrections is research: shared formats for device descriptions and receipts, equivalence checking for approximate and parametrised compilation, test circuits for mitigation claims, and decoder benchmarks.

## 7. A first deployment without money: allocation networks

Public research centres already grant quantum time by proposal and meter it in non-monetary units, much as they meter classical supercomputer hours. That makes a natural first deployment:

- each centre runs its own frame, with its own unit, policy and jurisdiction ([Sovereign frames](#/docs/18));
- centres federate and honour each other's allocations at a ratio they agree;
- every job leaves receipts, so results can be reproduced and cited, and a provider's or verifier's track record follows it between centres;
- the auditor checks that each centre's ledger conserves its units, so nothing appears outside a recorded grant; a cap per declared allocation is a rule to add.

Commercial billing, where it exists, stays in each provider's own contract. The network carries identity, authority, metering, evidence and audit. None of it needs money to change hands on the network.

## 8. A network that survives quantum computers

A large fault-tolerant quantum computer breaks the public-key cryptography most systems use today [1]. For us that means the Ed25519 signatures on registry cards, agent cards, credentials, federation licences and receipts; the elliptic-curve keys behind our workload certificates and the RSA keys behind our federation JWTs; and the key exchange inside our TLS. Symmetric keys, such as those behind session tokens, are not exposed the same way. Published estimates of the machine needed keep falling [11], and elliptic-curve keys need fewer logical qubits to break than RSA keys of comparable classical strength [10]. Our zero-knowledge proofs are exposed as well: UltraHonk rests on pairing-based polynomial commitments, so a large quantum computer could forge a proof, even though the Poseidon2 commitments inside the circuits hold.

For an accountability layer this matters twice: confidential circuits sent today can be recorded now and decrypted later, and a signature or proof made today must still mean something when someone checks the record years from now.

What already holds: hash commitments. Known quantum attacks weaken hash functions such as SHA-256 only modestly, so the digests in track-record receipts and the hash-chained liability evidence keep their value, as long as each chain's head is anchored where a quantum attacker cannot rewrite it. The frame ledger is append-only by access control, not by hashes. The auditor's conservation check is arithmetic, not cryptography.

The migration plan, none of it built yet:

1. Inventory every signature, key exchange, certificate and proof on the network.
2. Hybrid key exchange (a classical curve plus ML-KEM [12]) at the public edges and on internal mutual TLS. It needs no new certificates, and current open-source TLS libraries support it.
3. Dual signatures (classical plus ML-DSA) on long-lived artifacts first: registry cards, federation licences, receipts and liability evidence. Key sets publish both keys. A verifier that knows both algorithms requires both signatures; an older verifier keeps checking the classical one until it is retired. The list of algorithms sits inside the signed bytes, so neither signature can be stripped unnoticed.
4. Algorithm names inside every signed format, so the next change is configuration, not redesign.
5. Hash-link the frame ledger, and anchor chain heads and long-lived evidence where a quantum attacker cannot rewrite them: published and witnessed, or signed with a hash-based scheme such as SLH-DSA.
6. Workload certificates follow once SPIFFE tooling supports post-quantum certificates, and long-lived attestations move to a hash-based proof system when one fits the circuits.

The EU's coordinated roadmap [13] asks member states to start this transition by the end of 2026 and to complete it for high-risk uses by 2030.

## 9. Roadmap: possible today, if built

Each item uses rails that run now. None needs a new ledger, a new consensus mechanism or a new token.

1. A provider agent template that wraps a cloud QPU or a simulator and runs on the provider's own infrastructure: OpenQASM 3 in; counts and a signed receipt out.
2. A device-facts extension for agent cards: qubits, native gates, connectivity, calibration summary and queue, as signed, timestamped claims the directory can index.
3. A job receipt schema with hash links between steps.
4. Acceptance-test templates for rungs 1 and 2 on work orders and milestone contracts.
5. A compiler agent that is paid only after an equivalence check.
6. QPU metering with the resource-usage circuit: a meter agent publishes a log commitment for each job, and providers prove the shots they report against it.
7. An allocation-frame profile for research consortia, with a cap per declared allocation.
8. Post-quantum step one: the inventory, and hybrid key exchange on our TLS links.

## 10. What we will not build

- No proof of quantum work [14] and no mining. The network has no consensus problem to solve; each frame's ledger is checked by a separate auditor service.
- No new token, and nothing that pays holders.
- No markets in future compute capacity.
- No real-time error correction over the network.
- No claims of quantum advantage on anyone's behalf.

## 11. Open questions

- Which acceptance tests are cheap enough for sampling workloads, and how can test circuits be hidden from a provider without blind protocols?
- Can providers sign calibration data so that a later reader can check it against the run?
- When do verifiable blind protocols become practical, and for which workloads?
- Which standards should we adopt rather than invent: OpenQASM 3 or QIR for jobs, a device description schema, a receipt format?
- How should a frame express export-control and data-residency rules for quantum work?
- Post-quantum signatures are kilobytes rather than bytes. What does that do to card sizes, federation traffic and small frames? Which hash-based proof system fits the policy circuits?

The base is in place, so these questions are the work. We want to build the quantum side with people who know it better than we do.

## About this revision

The August 2025 paper started from a sound observation, that the hard part of using quantum computers at scale is the layer around the machine, and answered it with a new ledger built on proof of quantum work, with "probabilistic smart contracts" and with a hypothesis confidence score. This version keeps the observation and changes the answer:

- proof of quantum work and probabilistic smart contracts are dropped; statistics move into acceptance tests agreed before the run;
- real-time error decoding is no longer proposed as a network service;
- the verification ladder, the allocation networks and the post-quantum plan are new;
- the zero-knowledge layer is described as it is built, with its limits;
- the confidence score is replaced by a line between what runs and what is open.

Revision 2 (16 October 2026) describes the network as it runs today, two production frames, EU and ASIA; corrects the keys behind the workload certificates (elliptic-curve, not RSA); points the evidence link at the chapter that holds the track record; and is published under the documentation's licence, CC BY 4.0.

## References

1. P. W. Shor, "Polynomial-time algorithms for prime factorization and discrete logarithms on a quantum computer", SIAM Journal on Computing 26(5), 1997.
2. A. Broadbent, J. Fitzsimons, E. Kashefi, "Universal blind quantum computation", FOCS 2009.
3. J. F. Fitzsimons, E. Kashefi, "Unconditionally verifiable blind quantum computation", Physical Review A 96, 012303, 2017.
4. U. Mahadev, "Classical verification of quantum computations", FOCS 2018.
5. A. Gheorghiu, T. Kapourniotis, E. Kashefi, "Verification of quantum computation: an overview of existing approaches", Theory of Computing Systems 63, 2019.
6. A. Cross et al., "OpenQASM 3: a broader and deeper quantum assembly language", ACM Transactions on Quantum Computing 3(3), 2022.
7. L. Burgholzer, R. Wille, "Advanced equivalence checking for quantum circuits", IEEE Transactions on Computer-Aided Design of Integrated Circuits and Systems 40(9), 2021.
8. Google Quantum AI and collaborators, "Quantum error correction below the surface code threshold", Nature 638, 2025.
9. M. Liu et al., "Certified randomness using a trapped-ion quantum processor", Nature 640, 2025.
10. M. Roetteler, M. Naehrig, K. M. Svore, K. Lauter, "Quantum resource estimates for computing elliptic curve discrete logarithms", ASIACRYPT 2017.
11. C. Gidney, "How to factor 2048 bit RSA integers with less than a million noisy qubits", arXiv:2505.15917, 2025.
12. NIST, FIPS 203 (ML-KEM), FIPS 204 (ML-DSA) and FIPS 205 (SLH-DSA), 2024.
13. NIS Cooperation Group, "A coordinated implementation roadmap for the transition to post-quantum cryptography", 2025.
14. M. H. Amin et al., "Blockchain with proof of quantum work", arXiv:2503.14462, 2025 (discussed in the August 2025 paper, not adopted).
15. TheProtocol documentation, https://theprotocol.cloud/#/docs (chapters cited inline).
