<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">◎</span>
            <h3 class="tp-modal-title">CHANGE MEMBER ROLE</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <!-- Member info card -->
          <div class="tp-member-card">
            <div class="tp-mc-avatar" :style="avatarStyle(member?.role || 'member')">
              {{ member?.developer_name?.charAt(0).toUpperCase() || '?' }}
            </div>
            <div class="tp-mc-info">
              <div class="tp-mc-name">{{ member?.developer_name }}</div>
              <div class="tp-mc-email">{{ member?.developer_email }}</div>
            </div>
            <span :class="['tp-current-role', roleBadgeClass(member?.role || '')]">
              {{ (member?.role || '').toUpperCase() }}
            </span>
          </div>

          <!-- Arrow -->
          <div class="tp-role-arrow">
            <svg viewBox="0 0 16 10" fill="none" width="16" height="10"><path d="M1 5h14M10 1l4 4-4 4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>NEW ROLE</span>
          </div>

          <!-- Role selector -->
          <div class="tp-role-grid">
            <label
              v-for="role in roles"
              :key="role.value"
              :class="['tp-role-item', { 'tp-role-item--active': newRole === role.value, 'tp-role-item--current': member?.role === role.value }]"
              :style="newRole === role.value ? `border-color:${role.color};background:${role.bg}` : ''"
            >
              <input v-model="newRole" :value="role.value" type="radio" class="tp-sr-only" :disabled="member?.role === role.value" />
              <span class="tp-role-name" :style="newRole === role.value ? `color:${role.color}` : ''">{{ role.label }}</span>
              <span class="tp-role-desc">{{ role.desc }}</span>
              <span v-if="member?.role === role.value" class="tp-role-current-tag">CURRENT</span>
            </label>
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isUpdating">CANCEL</button>
          <button
            class="tp-btn tp-btn--primary"
            @click="handleSubmit"
            :disabled="isUpdating || !newRole || newRole === member?.role"
          >
            <span v-if="isUpdating" class="tp-spinner"></span>
            {{ isUpdating ? 'UPDATING...' : 'CONFIRM CHANGE' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'
import type { OrganizationMember } from '@/services/api/organizationService'

const props = defineProps<{ member: OrganizationMember | null }>()
const emit = defineEmits<{ close: []; updated: [] }>()
const organizationStore = useOrganizationStore()

const isUpdating = ref(false)
const newRole = ref(props.member?.role || 'member')

const roles = [
  { value: 'admin',  label: 'ADMIN',  desc: 'Manage teams and members', color: 'rgba(var(--nc-primary-rgb),0.9)',   bg: 'rgba(var(--nc-primary-rgb),0.07)'   },
  { value: 'member', label: 'MEMBER', desc: 'Access org resources',     color: 'rgba(41,182,246,0.9)',  bg: 'rgba(41,182,246,0.07)'  },
  { value: 'guest',  label: 'GUEST',  desc: 'Read-only access',         color: 'rgba(148,163,184,0.7)', bg: 'rgba(148,163,184,0.05)' }
]

function avatarStyle(role: string): string {
  switch (role) {
    case 'owner':  return 'background:rgba(255,215,0,0.15);color:#ffd700;border:1px solid rgba(255,215,0,0.25)'
    case 'admin':  return 'background:rgba(var(--nc-primary-rgb),0.12);color:rgba(var(--nc-primary-rgb),0.9);border:1px solid rgba(var(--nc-primary-rgb),0.2)'
    case 'member': return 'background:rgba(41,182,246,0.12);color:rgba(41,182,246,0.9);border:1px solid rgba(41,182,246,0.2)'
    default:       return 'background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.4);border:1px solid rgba(255,255,255,0.08)'
  }
}

function roleBadgeClass(role: string): string {
  const map: Record<string, string> = {
    owner: 'role--owner', admin: 'role--admin', member: 'role--member', guest: 'role--guest'
  }
  return map[role] || 'role--guest'
}

async function handleSubmit() {
  if (!props.member || !newRole.value || newRole.value === props.member.role) return
  isUpdating.value = true
  try {
    await organizationStore.updateMemberRole(props.member.developer_id, newRole.value)
    emit('updated')
  } catch (error) {
    console.error('Failed to update member role:', error)
  } finally {
    isUpdating.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';

.tp-member-card {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 14px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px; margin-bottom: 16px;
}
.tp-mc-avatar {
  width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; font-weight: 700;
}
.tp-mc-info { flex: 1; min-width: 0; }
.tp-mc-name { font-size: 0.88rem; font-weight: 500; color: rgba(226,232,240,0.85); }
.tp-mc-email { font-size: 0.7rem; color: rgba(148,163,184,0.38); margin-top: 2px; }
.tp-current-role {
  flex-shrink: 0;
  display: inline-flex; align-items: center;
  padding: 3px 9px; border-radius: 20px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; font-weight: 700; letter-spacing: 0.1em;
  border: 1px solid transparent;
}
.role--owner  { background: rgba(255,215,0,0.1); color: #ffd700; border-color: rgba(255,215,0,0.25); }
.role--admin  { background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.9); border-color: rgba(var(--nc-primary-rgb),0.22); }
.role--member { background: rgba(41,182,246,0.1); color: rgba(41,182,246,0.9); border-color: rgba(41,182,246,0.22); }
.role--guest  { background: rgba(255,255,255,0.05); color: rgba(148,163,184,0.6); border-color: rgba(255,255,255,0.1); }

.tp-role-arrow {
  display: flex; align-items: center; gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; letter-spacing: 0.12em;
  color: rgba(148,163,184,0.3); margin-bottom: 10px;
}
.tp-role-grid { display: flex; flex-direction: column; gap: 6px; }
.tp-role-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 14px;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 7px; cursor: pointer;
  background: rgba(255,255,255,0.02);
  transition: all 0.12s; position: relative;
}
.tp-role-item:hover { border-color: rgba(255,255,255,0.14); background: rgba(255,255,255,0.04); }
.tp-role-item--current { opacity: 0.45; cursor: default; pointer-events: none; }
.tp-role-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.5); min-width: 54px;
}
.tp-role-desc { font-size: 0.75rem; color: rgba(148,163,184,0.4); flex: 1; }
.tp-role-current-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.52rem; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.35);
  padding: 1px 6px; border: 1px solid rgba(255,255,255,0.06); border-radius: 3px;
}
.tp-sr-only { position: absolute; opacity: 0; pointer-events: none; }
</style>
