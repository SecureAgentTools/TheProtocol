// Guided Tour registry. To add a tour: write a `*.tour.ts`, import it, add it to TOURS.
import type { GuidedTour } from './tour.types'
import { firstStepsTour } from './tours/firstSteps.tour'
// §BRIDGE R8 (2026-08-19) — Mission Control became the bridge; it needed its own
// walkthrough rather than a passing mention inside onboarding.
import { missionControlTour } from './tours/missionControl.tour'
// §LITEBRIDGE (2026-08-21) — the same bridge without a GPU needs its own
// walkthrough: its anchors only exist in light mode, and the point it has to
// make (this is not a lesser view) cannot be made in a footnote on the other.
import { missionControlLiteTour } from './tours/missionControlLite.tour'
import { discoveryTour } from './tours/discovery.tour'
import { agentLifecycleTour } from './tours/agentLifecycle.tour'
import { organizationsTour } from './tours/organizations.tour'
import { agoraTour } from './tours/agora.tour'
import { tokenEconomicsTour } from './tours/tokenEconomics.tour'
import { fiatOnrampTour } from './tours/fiatOnramp.tour'
import { stakingTour } from './tours/staking.tour'
import { governanceTour } from './tours/governance.tour'
import { smartContractsTour } from './tours/smartContracts.tour'
import { cicdTour } from './tours/cicd.tour'
import { bundlesTour } from './tours/bundles.tour'
import { apiKeysTour } from './tours/api-keys.tour'
import { disputesTour } from './tours/disputes.tour'
import { attestationsTour } from './tours/attestations.tour'
import { reputationTour } from './tours/reputation.tour'
import { federationTour } from './tours/federation.tour'
import { pocketTour } from './tours/pocket.tour'
import { forgeTour } from './tours/forge.tour'
import { settingsTour } from './tours/settings.tour'
import { guildTour } from './tours/guild.tour'
// §COCKPITA (2026-08-31) — the desk gained a live ledger and two agent channels on
// registry-a; a surface whose whole argument is that four facts are different facts needs
// a walkthrough that teaches the distinctions, not a list of tiles.
import { cockpitDeskTour } from './tours/cockpitDesk.tour'
import { ourChatTour } from './tours/ourchat.tour'
import { opFirstStepsTour } from './tours/opFirstSteps.tour'
import { opWatchtowerTour } from './tours/opWatchtower.tour'
import { opFederationTour } from './tours/opFederation.tour'
import { opTreasuryTour } from './tours/opTreasury.tour'
import { opEnforcementTour } from './tours/opEnforcement.tour'
import { opAssistantTour } from './tours/opAssistant.tour'
// §TOURGAP (2026-08-04) — three surfaces that had shipped with no tour at all.
import { eventLedgerTour } from './tours/eventLedger.tour'
import { readingTheNetworkTour } from './tours/readingTheNetwork.tour'
import { galacticCommandTour } from './tours/galacticCommand.tour'
// §TOURGAP-2 (2026-08-05) — surfaces shipped in §FEPARITY R2/R3/R4 that had no tour.
import { webhooksTour } from './tours/webhooks.tour'
import { contractTemplatesTour } from './tours/contractTemplates.tour'
import { enforcementTour } from './tours/enforcement.tour'
import { fxDeskTour } from './tours/fxDesk.tour'
// REGAUTH (SPEC 2026-08-15) — the regulatory authorization rail.
import { jurisdictionTour } from './tours/jurisdiction.tour'

// §2026-06-26 — full guided-tour library: every major topic, each individually
// launchable from the TutorialHub "Guided Tours" rail. NOT auto-started — a new
// dev opts into whichever orientation they want (no first-run overload).
// §2026-07-09 — exception: the `pocket` tour auto-starts ONCE on a user's first
// /pocket/* visit (PocketShell, localStorage `pk_tour_done`); replay = More → App tour.
export const TOURS: GuidedTour[] = [
  firstStepsTour, // start here
  missionControlTour, // §BRIDGE R8 — the bridge, for people who already have a fleet
  missionControlLiteTour, // §LITEBRIDGE — the same bridge on a machine with no GPU
  cockpitDeskTour, // §COCKPITA — the consent desk: four facts per agent, and the one control that acts
  ourChatTour,     // §CHATCOHERE A2 — the chat's money model: what a thread costs, confirms and returns
  pocketTour, // mobile walkthrough (auto-starts once in Pocket)
  discoveryTour, agentLifecycleTour, organizationsTour,
  agoraTour, tokenEconomicsTour, fiatOnrampTour, stakingTour, governanceTour,
  smartContractsTour, cicdTour, bundlesTour, apiKeysTour,
  disputesTour, attestationsTour, reputationTour, federationTour,
  forgeTour, // GÖDEL FORGE self-improving arena (2026-07-19)
  settingsTour, // §OPGUIDE-8 — API keys + invitation codes in one walkthrough
  guildTour, // §TOURSERIES — the work exchange: post → bid → award → verify → pay
  // §TOURGAP (2026-08-04) — open to any logged-in dev: the three spatial views are
  // reachable without admin, and were the least-introduced surfaces in the product.
  readingTheNetworkTour,
  // §TOURGAP-2 — developer-tier, open to anyone logged in.
  webhooksTour, contractTemplatesTour,
  // §TOURSERIES (2026-08-02) — OPERATOR SERIES: admin-locked in the hub (requireAdmin,
  // granular requireFlag where one area fits). Non-admins see them locked, not hidden —
  // the lock label doubles as an explanation of what operating a node entails.
  opFirstStepsTour, opWatchtowerTour, opFederationTour,
  opTreasuryTour, opEnforcementTour, opAssistantTour,
  // §TOURGAP — the ledger the Δ numbers come from, and the fleet cockpit.
  eventLedgerTour, galacticCommandTour,
  // §TOURGAP-2 — the R2 enforcement console and the R3 FX desk.
  enforcementTour, fxDeskTour, jurisdictionTour,
]

export function getTour(id: string): GuidedTour | undefined {
  return TOURS.find((t) => t.id === id)
}
