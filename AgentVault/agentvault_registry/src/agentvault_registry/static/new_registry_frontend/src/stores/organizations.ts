import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { 
  organizationService, 
  type Organization, 
  type Team, 
  type OrganizationMember,
  type TeamMember,
  type CreateOrganizationRequest,
  type UpdateOrganizationRequest,
  type CreateTeamRequest,
  type UpdateTeamRequest,
  type InviteMemberRequest
} from '@/services/api/organizationService'
import { useAuthStore } from './auth'
import { useUIStore } from './ui'
// §FESUITE — a refusal is shown in the server's words (axios' error.message is "Request failed with status code 422")
import { messageOf } from '@/utils/httpError'

export const useOrganizationStore = defineStore('organizations', () => {
  // ==================
  // State
  // ==================
  const organizations = ref<Organization[]>([])
  const currentOrganization = ref<Organization | null>(null)
  // §FESUITE (the failing-reads census, 2026-10-04): the organizations' list answered (listRead), or its read failed or
  // never ran because the profile could not be read (listFailed). The dashboard said "No organizations found" either way.
  const listRead = ref(false)
  const listFailed = ref(false)
  // §FESUITE (V0577): the current organization's teams / members read got no answer. Each became [] without a word, so
  // the dashboard said "no teams" / "no members" (counts of 0) and, the viewer's role being read off the members, an
  // owner saw the organization as a stranger would, with every owner control gone.
  const teamsFailed = ref(false)
  const membersFailed = ref(false)
  const teams = ref<Team[]>([])
  const members = ref<OrganizationMember[]>([])
  const teamMembers = ref<Map<string, TeamMember[]>>(new Map())
  
  // Loading states
  const isLoading = ref(false)
  const isLoadingTeams = ref(false)
  const isLoadingMembers = ref(false)
  const isCreating = ref(false)
  const isUpdating = ref(false)
  const isDeleting = ref(false)
  const isInviting = ref(false)
  
  // UI state
  const selectedTeam = ref<Team | null>(null)
  const filters = ref({
    search: '',
    status: 'all',
    role: 'all'
  })

  // ==================
  // Computed
  // ==================
  const authStore = useAuthStore()
  
  const currentUserId = computed(() => {
    // Fix: Check multiple possible ID fields since backend might use developer_id
    return authStore.user?.developer_id || authStore.user?.id || null
  })
  
  const currentUserMember = computed(() => {
    if (!currentOrganization.value || !currentUserId.value) return null
    // Try to match by developer_id field (as integer)
    const userId = parseInt(String(currentUserId.value))
    return members.value.find(m => m.developer_id === userId)
  })
  
  const currentUserRole = computed(() => {
    return currentUserMember.value?.role || null
  })
  
  const canManageOrganization = computed(() => {
    return ['owner', 'admin'].includes(currentUserRole.value || '')
  })
  
  const canManageTeams = computed(() => {
    return ['owner', 'admin'].includes(currentUserRole.value || '')
  })
  
  const canInviteMembers = computed(() => {
    return ['owner', 'admin'].includes(currentUserRole.value || '')
  })
  
  const canRemoveMembers = computed(() => {
    return currentUserRole.value === 'owner'
  })
  
  const activeOrganizations = computed(() => {
    return organizations.value.filter(org => org.is_active)
  })
  
  const activeTeams = computed(() => {
    return teams.value.filter(team => team.is_active)
  })
  
  const activeMembers = computed(() => {
    return members.value.filter(member => member.is_active)
  })
  
  const ownerMember = computed(() => {
    return members.value.find(m => m.role === 'owner')
  })
  
  const adminMembers = computed(() => {
    return members.value.filter(m => m.role === 'admin')
  })
  
  const regularMembers = computed(() => {
    return members.value.filter(m => m.role === 'member')
  })
  
  const guestMembers = computed(() => {
    return members.value.filter(m => m.role === 'guest')
  })
  
  const organizationStats = computed(() => {
    if (!currentOrganization.value) return null
    
    return {
      memberCount: currentOrganization.value.member_count,
      teamCount: currentOrganization.value.team_count,
      memberLimit: currentOrganization.value.member_limit,
      teamLimit: currentOrganization.value.team_limit,
      agentLimit: currentOrganization.value.agent_limit,
      memberUsage: (currentOrganization.value.member_count / currentOrganization.value.member_limit) * 100,
      teamUsage: (currentOrganization.value.team_count / currentOrganization.value.team_limit) * 100
    }
  })

  // ==================
  // Organization Actions
  // ==================
  
  /**
   * Fetch all organizations for the current user
   */
  async function fetchOrganizations() {
    const uiStore = useUIStore()
    
    // Wait for auth to be ready
    if (!authStore.isAuthenticated || !authStore.user) {
      import.meta.env.DEV && console.log('Waiting for auth before fetching organizations...')
      // If auth is not ready, wait a bit and check again
      return new Promise((resolve) => {
        const checkAuth = setInterval(() => {
          if (authStore.isAuthenticated && authStore.user) {
            clearInterval(checkAuth)
            fetchOrganizations().then(resolve)
          }
        }, 100)
        
        // Timeout after 5 seconds
        setTimeout(() => {
          clearInterval(checkAuth)
          console.error('Auth timeout - cannot fetch organizations')
          listFailed.value = !listRead.value
          resolve([])
        }, 5000)
      })
    }
    
    isLoading.value = true
    
    try {
      import.meta.env.DEV && console.log('Fetching organizations with auth:', {
        isAuthenticated: authStore.isAuthenticated,
        user: authStore.user?.email,
        role: authStore.user?.role
      })
      
      organizations.value = await organizationService.listOrganizations()
      listRead.value = true
      listFailed.value = false
      
      // Update counts after fetching
      if (organizations.value.length > 0) {
        // Calculate counts from actual data if backend doesn't provide them
        organizations.value = organizations.value.map(org => ({
          ...org,
          member_count: org.member_count ?? 1, // At least the owner
          team_count: org.team_count ?? 1 // Default team
        }))
      }
      
      // Auto-select first organization if none selected
      if (organizations.value.length > 0 && !currentOrganization.value) {
        await selectOrganization(organizations.value[0].id)
      }
      
      return organizations.value
    } catch (error: any) {
      listFailed.value = !organizations.value.length
      console.error('List organizations error:', error)
      uiStore.showError('Failed to load organizations', messageOf(error?.response?.data, error?.message))
      throw error
    } finally {
      isLoading.value = false
    }
  }
  
  /**
   * Select an organization as current
   */
  async function selectOrganization(orgId: string) {
    const org = organizations.value.find(o => o.id === orgId)
    if (!org) {
      throw new Error('Organization not found')
    }
    
    // §FESUITE 135 (2026-10-15): another organization's lists never stand under this one's name while its own load
    if (currentOrganization.value?.id !== orgId) { teams.value = []; members.value = [] }
    currentOrganization.value = org
    
    // Load teams and members for this organization
    await Promise.all([
      fetchTeams(orgId),
      fetchMembers(orgId)
    ])
    
    // Update counts based on fetched data (only while this is still the organization picked: a quick A, then B, had
    // counted A's lists into B)
    if (currentOrganization.value && currentOrganization.value.id === orgId) {
      currentOrganization.value.member_count = members.value.length || currentOrganization.value.member_count || 0
      currentOrganization.value.team_count = teams.value.length || currentOrganization.value.team_count || 0
    }
    
    return org
  }
  
  /**
   * Create a new organization
   */
  async function createOrganization(data: CreateOrganizationRequest) {
    const uiStore = useUIStore()
    isCreating.value = true
    
    try {
      const newOrg = await organizationService.createOrganization(data)
      organizations.value.push(newOrg)
      
      // Auto-select the new organization
      await selectOrganization(newOrg.id)
      
      uiStore.showSuccess('Organization created', `${newOrg.name} has been created successfully`)
      return newOrg
    } catch (error: any) {
      uiStore.showError('Failed to create organization', messageOf(error?.response?.data, error?.message))
      throw error
    } finally {
      isCreating.value = false
    }
  }
  
  /**
   * Update current organization
   */
  async function updateOrganization(data: UpdateOrganizationRequest) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    isUpdating.value = true
    
    try {
      const updated = await organizationService.updateOrganization(
        currentOrganization.value.id,
        data
      )
      
      // Update in list
      const index = organizations.value.findIndex(o => o.id === updated.id)
      if (index !== -1) {
        organizations.value[index] = updated
      }
      
      // Update current if it's the same
      if (currentOrganization.value.id === updated.id) {
        currentOrganization.value = updated
      }
      
      uiStore.showSuccess('Organization updated', 'Changes saved successfully')
      return updated
    } catch (error: any) {
      uiStore.showError('Failed to update organization', messageOf(error?.response?.data, error?.message))
      throw error
    } finally {
      isUpdating.value = false
    }
  }
  
  /**
   * Delete an organization
   */
  async function deleteOrganization(orgId: string) {
    const uiStore = useUIStore()
    isDeleting.value = true
    
    try {
      await organizationService.deleteOrganization(orgId)
      
      // Remove from list
      organizations.value = organizations.value.filter(o => o.id !== orgId)
      
      // Clear current if it was deleted
      if (currentOrganization.value?.id === orgId) {
        currentOrganization.value = null
        teams.value = []
        members.value = []
        
        // Select another org if available
        if (organizations.value.length > 0) {
          await selectOrganization(organizations.value[0].id)
        }
      }
      
      uiStore.showSuccess('Organization deleted', 'Organization has been deleted')
    } catch (error: any) {
      uiStore.showError('Failed to delete organization', messageOf(error?.response?.data, error?.message))
      throw error
    } finally {
      isDeleting.value = false
    }
  }

  // ==================
  // Team Actions
  // ==================
  
  /**
   * Fetch teams for an organization
   */
  // §FESUITE 135 (2026-10-15): the latest call owns the list; an earlier call's answer (a quick A, then B) is dropped
  let teamsSeq = 0
  async function fetchTeams(orgId: string) {
    const mine = ++teamsSeq
    isLoadingTeams.value = true
    
    try {
      const list = await organizationService.listTeams(orgId)
      if (mine !== teamsSeq) return list
      teams.value = list
      teamsFailed.value = false
      return teams.value
    } catch (error: any) {
      if (mine !== teamsSeq) return
      console.error('Failed to fetch teams:', error)
      teams.value = []
      teamsFailed.value = true
    } finally {
      if (mine === teamsSeq) isLoadingTeams.value = false
    }
  }
  
  /**
   * Create a new team
   */
  async function createTeam(data: CreateTeamRequest) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    
    try {
      const newTeam = await organizationService.createTeam(
        currentOrganization.value.id,
        data
      )
      
      teams.value.push(newTeam)
      
      // Update team count
      if (currentOrganization.value) {
        currentOrganization.value.team_count++
      }
      
      uiStore.showSuccess('Team created', `${newTeam.name} has been created`)
      return newTeam
    } catch (error: any) {
      uiStore.showError('Failed to create team', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }
  
  /**
   * Update a team
   */
  async function updateTeam(teamId: string, data: UpdateTeamRequest) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    
    try {
      const updated = await organizationService.updateTeam(
        currentOrganization.value.id,
        teamId,
        data
      )
      
      // Update in list
      const index = teams.value.findIndex(t => t.id === teamId)
      if (index !== -1) {
        teams.value[index] = updated
      }
      
      // Update selected if it's the same
      if (selectedTeam.value?.id === teamId) {
        selectedTeam.value = updated
      }
      
      uiStore.showSuccess('Team updated', 'Changes saved successfully')
      return updated
    } catch (error: any) {
      uiStore.showError('Failed to update team', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }
  
  /**
   * Delete a team
   */
  async function deleteTeam(teamId: string) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    
    try {
      await organizationService.deleteTeam(currentOrganization.value.id, teamId)
      
      // Remove from list
      teams.value = teams.value.filter(t => t.id !== teamId)
      
      // Clear selected if it was deleted
      if (selectedTeam.value?.id === teamId) {
        selectedTeam.value = null
      }
      
      // Update team count
      if (currentOrganization.value) {
        currentOrganization.value.team_count--
      }
      
      uiStore.showSuccess('Team deleted', 'Team has been deleted')
    } catch (error: any) {
      uiStore.showError('Failed to delete team', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }

  // ==================
  // Member Actions
  // ==================
  
  /**
   * Fetch members for an organization
   */
  let membersSeq = 0
  async function fetchMembers(orgId: string) {
    const mine = ++membersSeq
    isLoadingMembers.value = true
    
    try {
      const list = await organizationService.listMembers(orgId)
      if (mine !== membersSeq) return list
      members.value = list
      membersFailed.value = false
      return members.value
    } catch (error: any) {
      if (mine !== membersSeq) return
      console.error('Failed to fetch members:', error)
      members.value = []
      membersFailed.value = true
    } finally {
      if (mine === membersSeq) isLoadingMembers.value = false
    }
  }
  
  /**
   * Invite a member to the organization
   */
  async function inviteMember(data: InviteMemberRequest) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    isInviting.value = true
    
    try {
      const invitation = await organizationService.inviteMember(
        currentOrganization.value.id,
        data
      )
      
      // §FESUITE (V0594): the registry says whether the mail went (it was "sent" whatever the send did). Without its mail
      // the invited person has no link to accept with; an older registry that does not say keeps the old sentence
      if (invitation?.mail_sent === false) {
        uiStore.showWarning(
          'Invitation created, mail not sent',
          `The invitation for ${data.email} was created, but its mail could not be sent, and without it they cannot accept. Withdraw it under Invitations and send a new one later.`
        )
      } else {
        uiStore.showSuccess(
          'Invitation sent',
          `An invitation has been sent to ${data.email}`
        )
      }
      
      // Refresh members list to show pending invitation
      await fetchMembers(currentOrganization.value.id)
      
      return invitation
    } catch (error: any) {
      uiStore.showError('Failed to send invitation', messageOf(error?.response?.data, error?.message))
      throw error
    } finally {
      isInviting.value = false
    }
  }
  
  /**
   * Remove a member from the organization
   */
  async function removeMember(developerId: number) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }

    const uiStore = useUIStore()

    try {
      // Backend keys members by DEVELOPER id (int), not the membership-row UUID.
      await organizationService.removeMember(currentOrganization.value.id, developerId)

      // Remove from list
      members.value = members.value.filter(m => m.developer_id !== developerId)
      
      // Update member count
      if (currentOrganization.value) {
        currentOrganization.value.member_count--
      }
      
      uiStore.showSuccess('Member removed', 'Member has been removed from the organization')
    } catch (error: any) {
      uiStore.showError('Failed to remove member', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }
  
  /**
   * Update a member's role
   */
  async function updateMemberRole(developerId: number, role: string) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }

    const uiStore = useUIStore()

    try {
      const updated = await organizationService.updateMemberRole(
        currentOrganization.value.id,
        developerId,
        role
      )

      // Update in list
      const index = members.value.findIndex(m => m.developer_id === developerId)
      if (index !== -1) {
        members.value[index] = updated
      }
      
      uiStore.showSuccess('Role updated', 'Member role has been updated')
      return updated
    } catch (error: any) {
      uiStore.showError('Failed to update role', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }
  
  /**
   * Accept an invitation
   */
  async function acceptInvitation(token: string) {
    const uiStore = useUIStore()
    
    try {
      await organizationService.acceptInvitation(token)
      
      uiStore.showSuccess('Invitation accepted', 'You have joined the organization')
      
      // Refresh organizations list
      await fetchOrganizations()
    } catch (error: any) {
      uiStore.showError('Failed to accept invitation', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }

  // ==================
  // Team Member Actions
  // ==================
  
  /**
   * Add a member to a team
   */
  async function addTeamMember(teamId: string, developerId: number, role: 'lead' | 'member' = 'member') {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    
    try {
      const teamMember = await organizationService.addTeamMember(
        currentOrganization.value.id,
        teamId,
        { developer_id: developerId, role }
      )
      
      // Update team members cache
      const currentMembers = teamMembers.value.get(teamId) || []
      currentMembers.push(teamMember)
      teamMembers.value.set(teamId, currentMembers)
      
      // Update team member count
      const team = teams.value.find(t => t.id === teamId)
      if (team && team.member_count !== undefined) {
        team.member_count++
      }
      
      uiStore.showSuccess('Member added', 'Member has been added to the team')
      return teamMember
    } catch (error: any) {
      uiStore.showError('Failed to add team member', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }
  
  /**
   * Fetch team members
   */
  async function fetchTeamMembers(teamId: string) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    try {
      const members = await organizationService.listTeamMembers(
        currentOrganization.value.id,
        teamId
      )
      
      // Cache the members
      teamMembers.value.set(teamId, members)
      
      return members
    } catch (error: any) {
      console.error('Failed to fetch team members:', error)
      return []
    }
  }
  
  /**
   * Remove a member from a team
   */
  async function removeTeamMember(teamId: string, developerId: number) {
    if (!currentOrganization.value) {
      throw new Error('No organization selected')
    }
    
    const uiStore = useUIStore()
    
    try {
      await organizationService.removeTeamMember(
        currentOrganization.value.id,
        teamId,
        developerId
      )
      
      // Update team members cache
      const currentMembers = teamMembers.value.get(teamId) || []
      const filtered = currentMembers.filter(m => m.developer_id !== developerId)
      teamMembers.value.set(teamId, filtered)
      
      // Update team member count
      const team = teams.value.find(t => t.id === teamId)
      if (team && team.member_count !== undefined) {
        team.member_count--
      }
      
      uiStore.showSuccess('Member removed', 'Member has been removed from the team')
    } catch (error: any) {
      uiStore.showError('Failed to remove team member', messageOf(error?.response?.data, error?.message))
      throw error
    }
  }

  // ==================
  // Utility Actions
  // ==================
  
  /**
   * Reset store state
   */
  function reset() {
    organizations.value = []
    listRead.value = false
    listFailed.value = false
    currentOrganization.value = null
    teams.value = []
    members.value = []
    teamsFailed.value = false
    membersFailed.value = false
    teamMembers.value.clear()
    selectedTeam.value = null
    filters.value = {
      search: '',
      status: 'all',
      role: 'all'
    }
  }

  return {
    // State
    organizations,
    listRead,
    listFailed,
    teamsFailed,
    membersFailed,
    currentOrganization,
    teams,
    members,
    teamMembers,
    isLoading,
    isLoadingTeams,
    isLoadingMembers,
    isCreating,
    isUpdating,
    isDeleting,
    isInviting,
    selectedTeam,
    filters,
    
    // Computed
    currentUserId,
    currentUserMember,
    currentUserRole,
    canManageOrganization,
    canManageTeams,
    canInviteMembers,
    canRemoveMembers,
    activeOrganizations,
    activeTeams,
    activeMembers,
    ownerMember,
    adminMembers,
    regularMembers,
    guestMembers,
    organizationStats,
    
    // Organization Actions
    fetchOrganizations,
    selectOrganization,
    createOrganization,
    updateOrganization,
    deleteOrganization,
    
    // Team Actions
    fetchTeams,
    createTeam,
    updateTeam,
    deleteTeam,
    
    // Member Actions
    fetchMembers,
    inviteMember,
    removeMember,
    updateMemberRole,
    acceptInvitation,
    
    // Team Member Actions
    addTeamMember,
    fetchTeamMembers,
    removeTeamMember,
    
    // Utility
    reset
  }
})
