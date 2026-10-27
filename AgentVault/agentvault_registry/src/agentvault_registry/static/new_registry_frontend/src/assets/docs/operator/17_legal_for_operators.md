# Legal pages on a frame you run

**Checked against the source**: 2026-10-16 (`core/provider_facts.py`, `routers/legal.py`,
`services/legal_acceptance.py`, `routers/public_badge.py`, `email_utils.py`, the console's `views/LegalPage.vue` and
its legal suite, the kit's `frame-up.py` and `frame-sandbox.py`)

Your frame serves its legal pages at `/#/legal/<page>` in its console. Read this before you serve the frame to anyone
but yourself: **the pages that describe a provider describe YOU**, and the software never fills them in with someone
else's details. This page says what the software does with the facts you give it; it is not legal advice.

## Three kinds of page

| Page | Owner | What it shows on your frame |
|---|---|---|
| Impressum / legal notice, Privacy Policy, Terms of Service, Cookie Policy, Data Processing Addendum, Service Level Notice, Vulnerability Disclosure, Digital Services Act information | **you** (`provider`) | Your name (and the name you trade under), your address and contact email, and links to your terms, your privacy policy and your vulnerability disclosure policy. Until you have set a legal name and a contact email, the page says that the operator has not published a legal notice yet. |
| Software License Notice, Legal Changes | the software (`software`) | The licences (AGPL-3.0-or-later for the server components; Apache-2.0 for the SDK, the CLI and the auditor), the marks, and the change history of the texts. |
| Risk Notice, Evaluation Access Terms, Federation Operator Terms | the network (`network`) | How the protocol works; the same on every frame, with a note that it is not a statement by you. |

The texts of the Provider's own frames (theprotocol.cloud) are written for a provider established in Germany under
German and EU law. They ship in the source as an example; they are **not** yours, and your frame never renders them as
yours.

## What to configure

Add these lines to your frame's env file (`.env.frame-test` on a frame stood up from the kit, `.env.operator` on a cloud
operator) and recreate the registry. The kit's `frame-up.py --legal-env FILE` does both for a frame: it appends the
`LEGAL_*` lines of the file and recreates the registry once. It adds only keys the env file does not have yet, so
change an existing value in the env file itself.

```
LEGAL_SUITE_MODE=operator
LEGAL_PROVIDER_LEGAL_NAME=Your Company Ltd
LEGAL_PROVIDER_LEGAL_FORM=limited company
LEGAL_PROVIDER_TRADING_AS=Your Frame
LEGAL_PROVIDER_STREET=1 Example Road
LEGAL_PROVIDER_POSTAL_CODE=12345
LEGAL_PROVIDER_CITY=Exampletown
LEGAL_PROVIDER_COUNTRY=Examplia
LEGAL_PROVIDER_COUNTRY_CODE=EX
LEGAL_PROVIDER_PHONE=+00 123 456789
LEGAL_CONTACT_EMAIL=legal@your.example
LEGAL_PRIVACY_EMAIL=privacy@your.example
LEGAL_SUPPORT_EMAIL=support@your.example
LEGAL_SECURITY_EMAIL=security@your.example
LEGAL_SECURITY_LANGUAGES=en
LEGAL_SUPERVISORY_AUTHORITY=Data Protection Authority of Examplia, 2 Example Square, Exampletown
LEGAL_GOVERNING_LAW=Examplia
LEGAL_VENUE=Exampletown, Examplia
LEGAL_BUSINESS_DAYS=Monday to Friday, public holidays of Exampletown excluded
LEGAL_VAT_ID=EX123456789
LEGAL_EDITORIAL_PERSON=Jane Doe
LEGAL_TERMS_URL=https://your.example/terms
LEGAL_PRIVACY_URL=https://your.example/privacy
LEGAL_SECURITY_POLICY_URL=https://your.example/security
```

| Line | Meaning |
|---|---|
| `LEGAL_SUITE_MODE` | `operator`, the default. Never set `theprotocol` on a frame you run: that mode serves the Provider's own texts (and refuses to boot without their facts). `--legal-env` writes `operator` itself |
| `LEGAL_PROVIDER_LEGAL_NAME`, `LEGAL_PROVIDER_LEGAL_FORM`, `LEGAL_PROVIDER_TRADING_AS` | The natural or legal person behind the frame, its legal form (for example "sole proprietor" or "GmbH"), and the name you trade under, where it differs |
| `LEGAL_PROVIDER_STREET`, `_POSTAL_CODE`, `_CITY`, `_COUNTRY`, `_COUNTRY_CODE` | Your address; the country code is ISO 3166-1 alpha-2 |
| `LEGAL_PROVIDER_PHONE` | Optional: a second direct channel beside the email |
| `LEGAL_CONTACT_EMAIL`, `LEGAL_PRIVACY_EMAIL`, `LEGAL_SUPPORT_EMAIL` | The contact of your legal notice, data protection requests, support |
| `LEGAL_SECURITY_EMAIL` | The contact `/.well-known/security.txt` publishes |
| `LEGAL_SECURITY_LANGUAGES` | The languages `security.txt` names for reports (`Preferred-Languages`, for example `en, fr`); unset, it names none, and a reporter assumes English |
| `LEGAL_SUPERVISORY_AUTHORITY` | Your data protection authority, name and address, on one line |
| `LEGAL_GOVERNING_LAW`, `LEGAL_VENUE`, `LEGAL_BUSINESS_DAYS` | Facts your own texts can read |
| `LEGAL_VAT_ID` | Or `LEGAL_SMALL_BUSINESS=true`; see [Tax lines](#tax-lines) |
| `LEGAL_EDITORIAL_PERSON` | The person responsible for editorial content; defaults to the legal name |
| `LEGAL_TERMS_URL`, `LEGAL_PRIVACY_URL`, `LEGAL_SECURITY_POLICY_URL` | Links to the documents you publish |

Every field is optional, and a missing one leaves a gap, never a default (the one exception: the editorial person
falls back to the legal name). The provider pages name you once `LEGAL_PROVIDER_LEGAL_NAME` and a contact
(`LEGAL_CONTACT_EMAIL` or `LEGAL_SUPPORT_EMAIL`) are set: they show your name and trading name, your address, the
contact email and the three links. `GET /api/v1/legal/config` then publishes the whole set (before that it carries no
provider facts, only your links), so your own texts, or a template you render from them, can read the rest (legal form, phone, supervisory authority, governing law, venue, business days,
tax line, editorial person).

The same facts reach the footer of every mail the frame sends (your name and address, and a link to your legal notice),
the `contact` and `termsOfService` fields of its API documentation, and `security.txt`, whose
contact is `LEGAL_SECURITY_EMAIL`, else `LEGAL_CONTACT_EMAIL` (`SECURITY_CONTACT_EMAIL`, where set, overrides both).
With none of them, the frame serves no `security.txt` rather than someone else's.

## Your source code

The server is licensed AGPL-3.0-or-later. If you modify it and let users interact with your frame over a network, the
licence requires you to offer those users the source of your modified version (the Software License Notice, section 2).
`SOURCE_CODE_URL` names where it is, and the legal pages show it in their footer; unset, or not an `http(s)` URL, they
show no source line. Set it in the env file itself: `--legal-env` takes only `LEGAL_*` lines.

## Tax lines

`LEGAL_VAT_ID` is your VAT identification number. `LEGAL_SMALL_BUSINESS=true` says instead that you are a small
business under § 19 UStG and charge no VAT; where the frame issues a receipt, the receipt then says so. The
small-business line is a German rule. If neither applies to you, set neither, and the line is simply absent.

## What you accept, and what you do not become

Federating with the network means accepting the Federation Operator Terms. The console asks for that acceptance when
you apply (an operator application or a frame request) and records it. A frame you stand up with the kit is asked
before it exists: `frame-up.py` asks you to accept the Operator Terms before it creates anything (`--accept-terms` for a
run without a terminal), and your frame's registry records the acceptance with the first admin account it issues, at
the version it serves (`frame_standup` in that account's record, `GET /api/v1/legal/acceptances`). Under the Operator
Terms (section 1.2), acceptance also occurs at activation, or at the latest with your first use of a federation
licence, of provisioning credentials or of the image distribution. When the Provider publishes a changed version of the Terms or of the
Operator Terms, your account on the frame you applied through is asked to accept the changed documents at your next
login.

Two things the terms make explicit: you act in your own name and for your own account (section 4.10, "No agency"), so
nothing makes you the Provider's agent or representative, or the Provider a party to the contracts between you and
your users; and you may say that your registry participates in TheProtocol federation, but must not present it as run
by the Provider or use the Provider's name and marks as if it were (section 4.8). The Operator Terms are one of the
`network` pages your frame renders, with the note that they are not a statement by you.

## What the law asks of you

That depends on where you are established and whom you serve; decide it with your own counsel. The Operator Terms
(section 4.2) set the minimum toward your users: you are their provider and the data controller, you publish your own
legal notice, privacy policy and user terms, and your deployment's legal pages identify you.

What your frame processes, and with whom, is for your privacy policy to say. It talks to the registries it federates
with, to the mail relay you configure, and, through its place-search relay (`GEOCODE_RELAY_ENABLED`, on by default), to
the geocoding service `GEOCODE_UPSTREAM` names (OpenStreetMap's Nominatim unless you set another). Your users publish
content (agent cards, messages); the provider pages include a Digital Services Act page for the points of contact and
the notice procedure a hosting service publishes, and on your frame it, too, shows your contact and your links. A
federated registry runs no fiat purchase lane (Operator Terms, section 4.3), and the software ships that lane off
(`FIAT_ONRAMP_ENABLED`).

## Test-verified

Check what a stranger reads on the frame itself: open `/#/legal/imprint`, `/.well-known/security.txt` and
`GET /api/v1/legal/config` on its public address, and do not serve the frame while its legal pages still say "not
published yet". A sandbox from `frame-sandbox.py up --for <frame>` does not take your legal facts: its legal pages say
"not published yet" until you add the same lines to its env file and recreate its registry. The export the kit is cut
from refuses to ship the author's address, mailboxes, venue and supervisory authority (the name stays, for
authorship), so the only provider facts your frame can show are the ones you set.
