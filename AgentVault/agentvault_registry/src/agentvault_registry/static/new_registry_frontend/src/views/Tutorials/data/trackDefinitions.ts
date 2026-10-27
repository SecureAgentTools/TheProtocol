import type { TutorialTrack } from '../types/tutorial.types'
import { agentLifecycleTrack } from './agentLifecycle.track'
import { tokenEconomicsTrack } from './tokenEconomics.track'
import { stakingGovernanceTrack } from './stakingGovernance.track'
import { federationTrack } from './federation.track'
import { disputesTrustTrack } from './disputesTrust.track'
import { federatedSettlementsTrack } from './federatedSettlements.track'
import { smartContractsTrack } from './smartContracts.track'
import { crossRegistryCommerceTrack } from './crossRegistryCommerce.track'
import { enforcementTrustTrack } from './enforcementTrust.track'
import { reputationSignalsTrack } from './reputationSignals.track'
import { attestationsComplianceTrack } from './attestationsCompliance.track'
import { fullAgentEconomyTrack } from './fullAgentEconomy.track'
import { agoraTradingTrack } from './agoraTrading.track'
import { organizationsTrack } from './organizations.track'
// REGAUTH (SPEC 2026-08-15) — the regulatory authorization rail.
import { jurisdictionTrack } from './jurisdiction.track'
import { agentCicdTrack } from './agentCicd.track'

/**
 * Master track registry.
 * All 12 tracks active (Phase 1-3A + Phase 4 + Phase 5 complete).
 *
 * Adding a new track requires ONLY:
 * 1. Create a new .track.ts data file
 * 2. Import it here
 * 3. Add it to the array
 * Zero new Vue components needed.
 */
export const allTracks: TutorialTrack[] = [
  agentLifecycleTrack,
  tokenEconomicsTrack,
  stakingGovernanceTrack,
  federationTrack,
  disputesTrustTrack,
  federatedSettlementsTrack,
  smartContractsTrack,
  crossRegistryCommerceTrack,
  enforcementTrustTrack,
  reputationSignalsTrack,
  attestationsComplianceTrack,
  fullAgentEconomyTrack,
  agoraTradingTrack,
  organizationsTrack,
  agentCicdTrack,
  jurisdictionTrack,
]

export function getTrackById(id: string): TutorialTrack | undefined {
  return allTracks.find(t => t.id === id)
}
