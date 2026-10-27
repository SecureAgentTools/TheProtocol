/**
 * §COCKPITFRAME F5 (2026-09-01) — ONE door per subject, for the whole desk.
 *
 * HIS ASK: *"make clickable things clickable and reuse existing modals if they exist."*
 *
 * Measured before building: of 25 panes, exactly TWO had any click-through, while NINE
 * rendered an agent identity with a DID already in hand and nothing behind it. The modals
 * were already there — `AgentDetailModal` (props: `show`, `agentDid`) and
 * `cicd/DeploymentLogsModal` (props: `deployment`, `agentDid`) — so this batch adds no new
 * surface, only the doors.
 *
 * 🔴 ONE OPENER, NOT ONE PER PANE. Nine panes each mounting their own modal is nine copies
 * of "open this agent", and two copies of one predicate is precisely how §ORGLEAK and
 * §HIRECOHERE happened. The desk mounts each modal ONCE, at the root, and every pane calls
 * this module.
 *
 * ⚠ MOUNTED AT THE ROOT ON PURPOSE, not inside the calling pane: every desk pane now lives
 * in a `PaneShell` whose body is `overflow: auto`, and a dialog opened inside a scroll
 * container inherits its clipping and its stacking context. The pane raises a fact; the
 * desk renders the dialog.
 *
 * ⚠ Module-level state, deliberately — the `usePrivacy` shape. Two independent copies of
 * "which agent is open" would let a second click on a different pane open a second dialog
 * behind the first.
 */
import { ref, computed } from 'vue'

/** The agent whose card is open, or null. */
const agentDid = ref<string | null>(null)
/** The name the caller already had, so the dialog's title is right before the fetch lands. */
const agentName = ref<string>('')

/** The deployment whose logs are open, with the agent it belongs to. */
const deployment = ref<any | null>(null)
const deploymentDid = ref<string>('')

/**
 * Open an agent's card.
 *
 * ⚠ A DID is required and validated here rather than at nine call sites: `AgentDetailModal`
 * fetches `/agents/by-did/<x>`, and a non-DID (an aggregate id, a name) is the §BRIDGE R9
 * defect — four 404s per page load and *"Agent card not found"* in front of the Commander.
 */
export function openAgent(did?: string | null, name = '') {
  const d = String(did || '')
  if (!d.startsWith('did:')) return
  agentName.value = name || ''
  agentDid.value = d
}
export function closeAgent() { agentDid.value = null; agentName.value = '' }

export function openDeployment(did?: string | null, row?: any) {
  const d = String(did || '')
  if (!d || !row || row.id === undefined || row.id === null) return
  deploymentDid.value = d
  deployment.value = row
}
export function closeDeployment() { deployment.value = null; deploymentDid.value = '' }

/** True for a DID this door can actually open — the test every link asks before rendering
 *  itself as a link. A door that leads nowhere is worse than no door (§DISCREFINE). */
export function isOpenable(did?: string | null): boolean {
  return String(did || '').startsWith('did:')
}

export function useAgentDoor() {
  return {
    agentDid, agentName, deployment, deploymentDid,
    agentOpen: computed(() => !!agentDid.value),
    deploymentOpen: computed(() => !!deployment.value),
    openAgent, closeAgent, openDeployment, closeDeployment, isOpenable,
  }
}
