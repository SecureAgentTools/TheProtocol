<template>
  <!-- V0657 (b), items 2 and 3: what the organization shows in public, and its logo, hosted by this registry. -->
  <section class="opf" data-testid="org-public-face" :data-listed="listed ? 'yes' : 'no'">
    <div class="opf__logo">
      <img v-if="logo && !broken" :src="logo" alt="" data-testid="org-public-face-logo" @error="broken = true" />
      <span v-else class="opf__glyph" aria-hidden="true">◈</span>
    </div>
    <div class="opf__body">
      <h3 class="opf__title">{{ t('orgFace.title', 'The organization in public') }}</h3>
      <p class="opf__state" data-testid="org-public-face-state">{{ listed
        ? t('orgFace.listed', 'Listed. Its name, logo, description and website are in the list of organizations across the federation, and its agents\' cards show its mark, here and on every peer (each agent can hide it).')
        : t('orgFace.unlisted', 'Not listed. Nothing about the organization leaves this registry, and no agent\'s card names it. "List this organization publicly" in the settings below turns it on.') }}</p>
      <div v-if="canEdit" class="opf__actions">
        <label class="tp-btn tp-btn--ghost opf__btn opf__upload">
          <input type="file" accept="image/png,image/jpeg" data-testid="org-logo-input" :disabled="busy" @change="onFile" />
          {{ logo ? t('orgFace.replace', 'Replace the logo') : t('orgFace.upload', 'Upload a logo') }}
        </label>
        <button v-if="logo" type="button" class="tp-btn tp-btn--ghost opf__btn" data-testid="org-logo-remove"
                :disabled="busy" @click="remove">{{ t('orgFace.remove', 'Remove the logo') }}</button>
        <span class="opf__hint">{{ t('orgFace.hint', 'A PNG or a JPEG, at most 256 KB. This registry hosts it, so a viewer\'s browser calls no other site.') }}</span>
      </div>
      <p v-if="error" class="opf__err" data-testid="org-logo-error">{{ error }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { organizationService } from '@/services/api/organizationService'

const props = defineProps<{ orgId: string; logo?: string | null; listed?: boolean; canEdit?: boolean }>()
const emit = defineEmits<{ (e: 'changed'): void }>()
const { t } = useI18n()
const busy = ref(false)
const error = ref('')
const broken = ref(false)
watch(() => props.logo, () => { broken.value = false })

const MAX = 256 * 1024

async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  error.value = ''
  if (file.size > MAX) {
    error.value = t('orgFace.tooBig', 'A logo is at most 256 KB.')
    return
  }
  if (!['image/png', 'image/jpeg'].includes(file.type)) {
    error.value = t('orgFace.wrongType', 'A logo is a PNG or a JPEG.')
    return
  }
  busy.value = true
  try {
    await organizationService.uploadLogo(props.orgId, file)
    emit('changed')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || t('orgFace.failed', 'The logo was not saved.')
  } finally {
    busy.value = false
  }
}

async function remove() {
  busy.value = true
  error.value = ''
  try {
    await organizationService.deleteLogo(props.orgId)
    emit('changed')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || t('orgFace.failed', 'The logo was not saved.')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';
.opf__btn { padding: 3px 10px; font-size: 11px; }
/* V0657 recut: the shared ghost button's 55% slate read #5a6779 on this panel's #141d2d, 2.93:1 (the console proof's
   a11y check); the same slate, opaque, reads 6.59:1 */
.opf__btn.tp-btn--ghost { color: #94a3b8; }
.opf { display: flex; gap: 14px; align-items: flex-start; padding: 12px; border: 1px solid rgba(148, 163, 184, .2);
  border-radius: 8px; margin-bottom: 16px; }
.opf__logo { flex: 0 0 56px; width: 56px; height: 56px; border-radius: 12px; overflow: hidden; display: flex;
  align-items: center; justify-content: center; background: rgba(148, 163, 184, .12); }
.opf__logo img { width: 100%; height: 100%; object-fit: cover; }
.opf__glyph { font-size: 22px; opacity: .6; }
.opf__body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.opf__title { margin: 0; font-size: 12px; font-weight: 600; }
.opf__state, .opf__hint { margin: 0; font-size: 12px; opacity: .8; }
.opf__actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.opf__upload input { display: none; }
.opf__err { margin: 0; font-size: 12px; color: #f87171; }
</style>
