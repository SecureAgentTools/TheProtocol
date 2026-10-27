<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">◎</span>
            <h3 class="tp-modal-title">INVITE MEMBER</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <div class="tp-field">
            <label class="tp-label">EMAIL ADDRESS <span class="tp-required">*</span></label>
            <input
              v-model="formData.email"
              type="email"
              class="tp-input"
              placeholder="member@example.com"
              required
              autofocus
            />
          </div>

          <div class="tp-field">
            <label class="tp-label">ROLE <span class="tp-required">*</span></label>
            <div class="tp-role-grid">
              <label
                v-for="role in roles"
                :key="role.value"
                :class="['tp-role-item', { 'tp-role-item--active': formData.role === role.value }]"
                :style="formData.role === role.value ? `border-color:${role.color};background:${role.bg}` : ''"
              >
                <input v-model="formData.role" :value="role.value" type="radio" class="tp-sr-only" />
                <span class="tp-role-name" :style="formData.role === role.value ? `color:${role.color}` : ''">{{ role.label }}</span>
                <span class="tp-role-desc">{{ role.desc }}</span>
              </label>
            </div>
          </div>

          <div class="tp-info-banner">
            <svg viewBox="0 0 16 16" fill="none" width="14" height="14" class="tp-info-icon"><circle cx="8" cy="8" r="6.5" stroke="currentColor" stroke-width="1.2"/><path d="M8 7v5M8 5.5v.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
            Invitation expires in 7 days. The invited member will receive instructions to join.
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isInviting">CANCEL</button>
          <button class="tp-btn tp-btn--primary" @click="handleSubmit" :disabled="isInviting || !formData.email">
            <span v-if="isInviting" class="tp-spinner"></span>
            {{ isInviting ? 'SENDING...' : 'SEND INVITATION' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'

const emit = defineEmits<{ close: []; invited: [] }>()
const organizationStore = useOrganizationStore()

const isInviting = ref(false)
const formData = ref({ email: '', role: 'member' as 'admin' | 'member' | 'guest' })

const roles = [
  { value: 'admin',  label: 'ADMIN',  desc: 'Manage teams and members', color: 'rgba(var(--nc-primary-rgb),0.9)',   bg: 'rgba(var(--nc-primary-rgb),0.07)'  },
  { value: 'member', label: 'MEMBER', desc: 'Access org resources',     color: 'rgba(41,182,246,0.9)',  bg: 'rgba(41,182,246,0.07)' },
  { value: 'guest',  label: 'GUEST',  desc: 'Read-only access',         color: 'rgba(148,163,184,0.7)', bg: 'rgba(148,163,184,0.05)' }
]

async function handleSubmit() {
  if (!formData.value.email) return
  isInviting.value = true
  try {
    await organizationStore.inviteMember({ email: formData.value.email, role: formData.value.role })
    emit('invited')
  } catch (error) {
    console.error('Failed to invite member:', error)
  } finally {
    isInviting.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';

.tp-role-grid { display: flex; flex-direction: column; gap: 6px; }
.tp-role-item {
  display: flex; flex-direction: column; gap: 2px;
  padding: 10px 14px;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 7px; cursor: pointer;
  background: rgba(255,255,255,0.02);
  transition: all 0.12s;
}
.tp-role-item:hover { border-color: rgba(255,255,255,0.14); background: rgba(255,255,255,0.04); }
.tp-role-item--active { border-color: rgba(var(--nc-primary-rgb),0.3); }
.tp-role-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.6);
}
.tp-role-desc { font-size: 0.75rem; color: rgba(148,163,184,0.4); }
.tp-sr-only { position: absolute; opacity: 0; pointer-events: none; }
</style>
