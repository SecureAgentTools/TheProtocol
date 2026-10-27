<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <!-- Header -->
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">⬡</span>
            <h3 class="tp-modal-title">CREATE ORGANIZATION</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <!-- Body -->
        <div class="tp-modal-body">
          <div class="tp-field">
            <label class="tp-label" for="org-create-name">ORGANIZATION NAME <span class="tp-required">*</span></label>
            <input
              id="org-create-name"
              v-model="formData.name"
              type="text"
              class="tp-input"
              placeholder="My Organization"
              maxlength="255"
              @input="generateSlug"
              required
              autofocus
              :aria-invalid="nameTooShort"
            />
            <!-- §FESUITE — the server takes 3 to 255 characters; a shorter name used to leave the page and come back as
                 "Request failed with status code 422". -->
            <p v-if="nameTooShort" class="tp-hint" role="status" data-testid="org-create-name-hint">
              {{ t('organizationDashboardView.nameTooShort', 'A name needs at least 3 characters.') }}
            </p>
          </div>

          <div class="tp-field">
            <label class="tp-label" for="org-create-slug">URL SLUG</label>
            <div class="tp-slug-row">
              <span class="tp-slug-prefix">theprotocol.cloud/org/</span>
              <input
                id="org-create-slug"
                maxlength="100"
                v-model="formData.slug"
                type="text"
                class="tp-input tp-input--slug"
                placeholder="my-organization"
                pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
              />
            </div>
            <p class="tp-hint">Lowercase letters, numbers, and hyphens only</p>
          </div>

          <div class="tp-field">
            <label class="tp-label" for="org-create-description">DESCRIPTION</label>
            <textarea
              id="org-create-description"
              maxlength="1000"
              v-model="formData.description"
              class="tp-input tp-textarea"
              rows="3"
              placeholder="Brief description of your organization"
            ></textarea>
          </div>

          <div class="tp-field">
            <label class="tp-label" for="org-create-website">WEBSITE</label>
            <input
              id="org-create-website"
              maxlength="500"
              v-model="formData.website"
              type="url"
              class="tp-input"
              placeholder="https://example.com"
            />
          </div>

          <!-- §OCOPTIN (2026-08-28): transparency is a CREATION-TIME choice too.
               Default off, forever; the copy states plainly what it exposes. -->
          <div class="tp-field">
            <label class="tp-check-row" data-testid="org-create-transparency">
              <input v-model="formData.transparencyOptIn" type="checkbox" class="tp-check" />
              <span>
                <span class="tp-label" style="display:block">PUBLIC WORK-RECORD TRANSPARENCY</span>
                <span class="tp-hint" style="margin:0">Publishes this organization's work records: treasury, distribution and guild receipt cards, system rows and the room topic, on a public read-only feed. Members' written messages are never included. You can turn this off at any time in Settings.</span>
              </span>
            </label>
          </div>
        </div>

        <!-- Footer -->
        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isCreating">CANCEL</button>
          <button class="tp-btn tp-btn--primary" @click="handleSubmit" :disabled="!canCreate">
            <span v-if="isCreating" class="tp-spinner"></span>
            {{ isCreating ? 'CREATING...' : 'CREATE ORGANIZATION' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'
import { useI18n } from '@/composables/useI18n'
import type { Organization } from '@/services/api/organizationService'

const emit = defineEmits<{ close: []; created: [organization: Organization] }>()
const organizationStore = useOrganizationStore()

const { t } = useI18n()
const isCreating = ref(false)
const formData = ref({ name: '', slug: '', description: '', website: '', transparencyOptIn: false })
const nameLength = computed(() => formData.value.name.trim().length)
const nameTooShort = computed(() => nameLength.value > 0 && nameLength.value < 3)
const canCreate = computed(() => !isCreating.value && nameLength.value >= 3 && nameLength.value <= 255)

function generateSlug() {
  if (!formData.value.slug || formData.value.slug === slugify(formData.value.name.slice(0, -1))) {
    formData.value.slug = slugify(formData.value.name)
  }
}

function slugify(text: string): string {
  return text.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-').trim()
}

async function handleSubmit() {
  // one press, one organization: a second press while the first is in flight is refused here too
  if (!canCreate.value) return
  isCreating.value = true
  try {
    const organization = await organizationStore.createOrganization({
      name: formData.value.name.trim(),
      slug: formData.value.slug || slugify(formData.value.name.trim()),
      description: formData.value.description || undefined,
      website: formData.value.website || undefined,
      // §OCOPTIN — only send settings when opted in; default stays server-side false
      settings: formData.value.transparencyOptIn ? { public_transparency_opt_in: true } : undefined
    })
    emit('created', organization)
  } catch (error) {
    console.error('Failed to create organization:', error)
  } finally {
    isCreating.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';
</style>
