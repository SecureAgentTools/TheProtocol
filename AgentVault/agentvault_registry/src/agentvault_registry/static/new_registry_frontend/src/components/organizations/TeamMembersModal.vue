<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal tp-modal--wide">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">◈</span>
            <div>
              <h3 class="tp-modal-title">TEAM MEMBERS</h3>
              <div class="tp-modal-subtitle">{{ team?.name }}</div>
            </div>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <!-- Add member row -->
          <div v-if="canManageTeam" class="tp-add-row">
            <select aria-label="Organization member to add" v-model="selectedMemberId" :disabled="isAddingMember" class="tp-input tp-select tp-select--grow">
              <option value="">Select org member to add...</option>
              <option v-for="m in availableMembers" :key="m.id" :value="m.developer_id">
                {{ m.developer_name }} — {{ m.developer_email }}
              </option>
            </select>
            <button class="tp-btn tp-btn--primary" @click="addMemberToTeam" :disabled="!selectedMemberId || isAddingMember">
              <span v-if="isAddingMember" class="tp-spinner"></span>
              {{ isAddingMember ? 'ADDING...' : '+ ADD' }}
            </button>
          </div>

          <!-- Loading -->
          <div v-if="isLoading" class="tp-loading-row">
            <div class="tp-spinner tp-spinner--lg"></div>
          </div>

          <!-- Empty -->
          <div v-else-if="teamMembersList.length === 0" class="tp-empty-sm">
            <span class="tp-empty-icon">◎</span>
            <p>No members in this team yet.</p>
          </div>

          <!-- Members list -->
          <div v-else class="tp-member-list">
            <div v-for="member in teamMembersList" :key="member.id" class="tp-member-row">
              <div class="tp-member-avatar" :style="avatarStyle(member.role)">
                {{ member.developer_name.charAt(0).toUpperCase() }}
              </div>
              <div class="tp-member-info">
                <div class="tp-member-name">{{ member.developer_name }}</div>
                <div class="tp-member-email">{{ member.developer_email }}</div>
              </div>
              <span :class="['tp-team-role', member.role === 'lead' ? 'tp-team-role--lead' : 'tp-team-role--member']">
                {{ member.role === 'lead' ? 'LEAD' : 'MEMBER' }}
              </span>
              <button
                v-if="canManageTeam && member.developer_id !== currentUserId"
                class="tp-remove-btn"
                @click="removeMemberFromTeam(member)"
                :disabled="isRemovingMember === member.id"
                title="Remove from team"
              >
                <svg viewBox="0 0 14 14" fill="none" width="12" height="12"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
              </button>
            </div>
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')">CLOSE</button>
        </div>
      </div>
    </div>

    <!-- OD4 (audit 2026-05-07): themed confirm for remove-from-team -->
    <ConfirmActionModal
      :show="showRemoveFromTeamModal"
      title="// REMOVE FROM TEAM"
      :message="teamMemberToRemove
        ? `Remove <strong>${teamMemberToRemove.developer_name}</strong> from this team? They stay in the organization but lose this team's permissions.`
        : ''"
      tone="warn"
      confirm-text="Remove"
      busy-text="Removing…"
      :busy="removeFromTeamBusy"
      @close="showRemoveFromTeamModal = false; teamMemberToRemove = null"
      @confirm="confirmRemoveFromTeam"
    />
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import type { Team } from '@/services/api/organizationService'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'

const props = defineProps<{ team: Team }>()
defineEmits<{ close: [] }>()

const organizationStore = useOrganizationStore()
const authStore = useAuthStore()
const uiStore = useUIStore()

const isLoading = ref(false)
const isAddingMember = ref(false)
const isRemovingMember = ref<string | null>(null)
const selectedMemberId = ref('')
const teamMembersList = ref<any[]>([])

const currentUserId = computed(() => authStore.user?.developer_id || authStore.user?.id)
const canManageTeam = computed(() => organizationStore.canManageTeams)
const availableMembers = computed(() => {
  const ids = teamMembersList.value.map(m => m.developer_id)
  return organizationStore.members.filter(m => !ids.includes(m.developer_id))
})

function avatarStyle(role: string): string {
  if (role === 'lead') return 'background:rgba(224,64,251,0.12);color:#e040fb;border:1px solid rgba(224,64,251,0.2)'
  return 'background:rgba(var(--nc-primary-rgb),0.1);color:rgba(var(--nc-primary-rgb),0.85);border:1px solid rgba(var(--nc-primary-rgb),0.18)'
}

onMounted(async () => {
  isLoading.value = true
  try {
    teamMembersList.value = organizationStore.members.filter(m => m.role !== 'guest').slice(0, 1)
  } finally {
    isLoading.value = false
  }
})

async function addMemberToTeam() {
  if (!selectedMemberId.value) return
  isAddingMember.value = true
  try {
    const member = organizationStore.members.find(m => m.developer_id === parseInt(selectedMemberId.value))
    if (member) {
      teamMembersList.value.push({ ...member, role: 'member' })
      selectedMemberId.value = ''
      uiStore.showSuccess('Member added', `${member.developer_name} added to team`)
    }
  } catch (error: any) {
    uiStore.showError('Failed to add member', error.message)
  } finally {
    isAddingMember.value = false
  }
}

// OD4 (audit 2026-05-07): replaced native confirm() with themed modal.
const showRemoveFromTeamModal = ref(false)
const teamMemberToRemove = ref<any>(null)
const removeFromTeamBusy = ref(false)

function removeMemberFromTeam(member: any) {
  teamMemberToRemove.value = member
  showRemoveFromTeamModal.value = true
}
async function confirmRemoveFromTeam() {
  const member = teamMemberToRemove.value
  if (!member) return
  removeFromTeamBusy.value = true
  isRemovingMember.value = member.id
  try {
    teamMembersList.value = teamMembersList.value.filter(m => m.id !== member.id)
    uiStore.showSuccess('Member removed', `${member.developer_name} removed from team`)
    showRemoveFromTeamModal.value = false
    teamMemberToRemove.value = null
  } catch (error: any) {
    uiStore.showError('Failed to remove member', error.message)
  } finally {
    isRemovingMember.value = null
    removeFromTeamBusy.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';

.tp-add-row { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; }
.tp-select { appearance: none; cursor: pointer; }
.tp-select--grow { flex: 1; }
.tp-loading-row { display: flex; justify-content: center; padding: 32px; }
.tp-empty-sm {
  display: flex; align-items: center; gap: 10px;
  padding: 24px; justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; color: rgba(148,163,184,0.35);
}
.tp-empty-icon { font-size: 1.1rem; color: rgba(148,163,184,0.2); }
.tp-member-list { display: flex; flex-direction: column; gap: 6px; max-height: 320px; overflow-y: auto; }
.tp-member-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 14px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 7px;
  transition: background 0.1s;
}
.tp-member-row:hover { background: rgba(var(--nc-primary-rgb),0.03); }
.tp-member-avatar {
  width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 700;
}
.tp-member-info { flex: 1; min-width: 0; }
.tp-member-name { font-size: 0.85rem; font-weight: 500; color: rgba(226,232,240,0.85); }
.tp-member-email { font-size: 0.7rem; color: rgba(148,163,184,0.38); margin-top: 1px; }
.tp-team-role {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 2px 8px; border-radius: 3px; flex-shrink: 0;
}
.tp-team-role--lead   { background: rgba(224,64,251,0.1); color: #e040fb; border: 1px solid rgba(224,64,251,0.2); }
.tp-team-role--member { background: rgba(var(--nc-primary-rgb),0.08); color: rgba(var(--nc-primary-rgb),0.8); border: 1px solid rgba(var(--nc-primary-rgb),0.15); }
.tp-remove-btn {
  background: none; border: 1px solid transparent; border-radius: 4px;
  color: rgba(239,68,68,0.35); cursor: pointer; padding: 4px;
  transition: all 0.12s; flex-shrink: 0;
}
.tp-remove-btn:hover { border-color: rgba(239,68,68,0.3); color: rgba(239,68,68,0.8); background: rgba(239,68,68,0.06); }
.tp-remove-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.tp-spinner--lg { width: 28px; height: 28px; border-width: 2px; }
</style>
