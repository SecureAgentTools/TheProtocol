# Jurisdiction Profiles

**Status**: Implemented, dark by default (`JURISDICTION_MODE=off`) · Spec: 2026-07-31 · Revised: 2026-10-03 (the worked example names the production frames) · Scope: every registry running this software

> **This document describes a mechanism, not legal advice.** The Protocol supplies the machinery for a deployment to declare and enforce which feature surfaces it runs. Choosing the profile, and determining what the law applicable to that deployment requires, is the responsibility of the operator running it. We deliberately publish no country-to-profile mapping (see §6).

## 1. What a jurisdiction profile is

Every economically meaningful surface on this platform is separately switchable: the AGORA organization market, cross-frame FX, the Guild work exchange, the Forge evaluation arena, the fiat purchase lane, and cross-registry transfers. A **jurisdiction profile** is a short, signed, machine-checked declaration by the operator of a deployment saying which of those surfaces are permitted to run there, plus optional limits.

The profile is declarative, deny-only, and evaluated before any value moves. It cannot create authority; it can only withhold it.

## 2. The profile document

```json
{
  "name": "conservative-markets-off",
  "version": 1,
  "features": {
    "exchange": false,
    "fx": false,
    "guild": true,
    "forge": true,
    "fiat": false,
    "cross_transfer": true
  },
  "limits": { "max_transfer_amount": 100000 }
}
```

Rules that keep the semantics honest:

- **No profile declared means no restriction declared.** An absent profile allows everything, exactly as before the feature existed.
- **Declaring restricts, never widens.** A feature omitted from a declared profile stays allowed, because a partial declaration must not be harsher than no declaration.
- **The feature vocabulary is closed.** Unknown feature or limit keys are rejected when the profile is submitted, so a deployment can never silently misread a newer profile.
- **A broken declaration fails open, loudly.** If the stored profile is unparseable it is treated as absent and logged as an error. A malformed compliance document must not freeze a running frame; it must be visible and fixed.

## 3. How it is enforced

`JURISDICTION_MODE` has three settings, the same ratchet used by the platform's other policy layers:

| Mode | Behaviour |
|---|---|
| `off` | Byte-inert. One settings read on gated paths, nothing else. |
| `shadow` | Every gated request is evaluated, decisions are logged and counted, nothing is blocked. This is how an operator measures the impact of a profile before arming it. |
| `enforce` | A denied request is refused with HTTP 403 and a machine-readable problem document naming the feature and the profile. |

Gates sit at the entry of each feature: order placement and launch purchase (AGORA), FX quoting, Guild task posting, cross-registry transfer (including the amount ceiling), fiat checkout, and Forge eval runs. Every gate runs **before** escrow or any ledger movement, so a denial can never leave value in an intermediate state and the supply invariant is untouched by design.

## 4. Verifiable in public: the registry card

When a profile is declared, the deployment's signed registry card gains a `compliance.jurisdiction_profile` block carrying the profile name, version, the list of denied features, the declaration timestamp, and a hash of the profile document. The registry card is already Ed25519-signed and synchronized across the federation, so the declaration becomes an attestation that peers, the independent auditor, and any member of the public can fetch and verify at `/.well-known/registry-card.json`.

A compliance claim that lives only inside one operator's database is not verifiable by anyone. On the card, it is.

The card block appears from `registry_card_version` **0.5** onward. The version was raised because the served card gained a signed field, not merely a new value: peers re-pull once on the change, which is the correct behaviour when the shape moves.

### 4.1 Where a declared profile is visible

The profile is read-only in every interface. It is derived from the profile document, and the only way to change it is the admin API in §8, so no screen offers an edit control that could drift from the signed source.

| Surface | Path | Shows |
|---|---|---|
| Registry card view | `/ui#/admin/registry-card` | Section "Jurisdiction profile / DERIVED": name, version, denied features, declaration timestamp, truncated profile hash |
| Registry card modal | Galactic Map, Universe, Discovery, Agent World | The same block for **any** registry whose card carries one, including peers |
| Signed card | `/.well-known/registry-card.json` | `compliance.jurisdiction_profile` |
| Policy console | `/ui#/admin/opa` | `agentvault.jurisdiction` under the invariant policies, with its rules and source |

If no profile is declared the section is absent everywhere, by design: a registry that has declared nothing should not display an empty compliance panel implying it has.

### 4.2 A declared profile under `JURISDICTION_MODE=off`

Declaring a profile and arming the gate are separate acts, and a deployment can legitimately do the first without the second. The production frames are the worked example: EU and ASIA each publish a profile denying `fiat` while their own jurisdiction gate is not armed (it runs in `shadow`: decisions are logged, nothing is blocked).

That is coherent rather than contradictory, and the distinction is worth stating precisely because it is easy to get wrong in the other direction. The claim is true because `FIAT_ONRAMP_ENABLED=false` enforces it, not because the gate does. A declaration is only publishable when something enforces it; which mechanism does the enforcing is an implementation detail, and the card is entitled to state the fact.

The failure to avoid is the inverse: declaring a feature denied while it remains switched on and unenforced. That is a signed claim the deployment does not honour, and it is exactly what the coherence rule in §5 detects.

## 5. Policy as an auditable artifact

The same semantics are expressed as an Open Policy Agent policy (`agentvault_jurisdiction.rego`). It exists for three reasons that the application code cannot serve: an auditor can read a declarative policy but not a scattered set of conditionals; the platform's policy console can replay real recorded traffic against a candidate profile and report exactly what would begin to be denied before it is armed; and it carries a coherence rule that compares the declaration against the deployment's live feature flags. A deployment whose profile denies a feature that is still switched on is publishing a claim it does not honour, and that mismatch is a defect worth surfacing.

## 6. Why there is no country list here

It would be easy to ship profiles named after jurisdictions. We do not, on purpose. An operator following a mapping we authored would be relying on our legal analysis of their situation, in their country, for their business. That is advice we are not qualified to give and not willing to imply. Instead we ship two neutral examples:

- **conservative**: markets and money-adjacent surfaces off, collaboration surfaces on.
- **full**: nothing restricted (identical in effect to declaring no profile, but explicit).

An operator, with their own counsel, decides what their deployment runs. The Federation Operator Terms make this explicit: the profile is part of the canonical parameters an operator maintains, and the operator warrants that their declaration satisfies the law applicable to them.

## 7. What this does and does not achieve

It **does**: make an operator's compliance posture explicit, enforced in code, published as a signed attestation, and checkable by third parties; give operators a safe way to run a restricted subset of the network; and provide the evidence trail that compliance frameworks ask for.

It **does not**: transfer legal responsibility for a deployment away from whoever operates it, nor relieve the platform provider of responsibility for the deployments the provider itself operates. A profile is a truthful statement about a system's configuration. It is not a shield, and this documentation will never describe it as one.

## 8. Administration

`GET`, `PUT`, and `DELETE` on `/api/v1/admin/jurisdiction-profile`, restricted to platform administrators of that deployment. Submissions are schema-validated, timestamped server-side, written to the security audit log at warning severity (a change in compliance posture should stand out), and reflected in the next registry card build.
