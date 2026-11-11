<template>
  <section v-if="canFix && !shows" class="omw" data-testid="org-mark-why" :data-missing="missing.join(' ')">
    <!-- V0658 (r): to the people who can change it, why the organization's mark does not show (V0657 (b): the mark only
         while it is listed, and its logo only when this registry hosts it), each reason with the one control that
         fixes it, and an old logo address's image offered for upload. Anyone else gets nothing, not even a comment. -->
    <p class="omw__title" data-testid="org-mark-why-title">{{ t('orgMarkWhy.title', 'Why its logo does not show') }}</p>
    <ul class="omw__list">
      <li v-if="gaps.listing" class="omw__row" data-testid="org-mark-why-listing">
        <p class="omw__why">{{ t('orgMarkWhy.notListed', 'It is not listed, so nothing about it leaves this registry and no agent\'s card names it. Listing it puts its name, logo, description and website in the list of organizations across the federation, and its mark on its agents\' cards (each agent can hide it).') }}</p>
        <button type="button" class="omw__btn" data-testid="org-mark-why-list" :disabled="busy" @click="list">
          {{ t('orgMarkWhy.listBtn', 'List this organization publicly') }}
        </button>
      </li>
      <li v-if="gaps.logo" class="omw__row" data-testid="org-mark-why-logo">
        <p class="omw__why">{{ t('orgMarkWhy.noLogo', 'No logo is hosted here. Only a logo this registry hosts is shown: a PNG or a JPEG of at most 256 KB.') }}</p>
        <label v-if="uploadHere" class="omw__btn omw__upload">
          <input type="file" accept="image/png,image/jpeg" data-testid="org-mark-why-upload" :disabled="busy" @change="onFile" />
          {{ t('orgFace.upload', 'Upload a logo') }}
        </label>
        <p v-else class="omw__hint" data-testid="org-mark-why-upload-below">{{ t('orgMarkWhy.uploadBelow', '"Upload a logo" below adds one.') }}</p>
      </li>
      <li v-if="gaps.legacy" class="omw__row omw__row--legacy" data-testid="org-mark-why-legacy">
        <!-- the registry never fetches it; the owner's own browser asks that host (an https address, no referrer) only when
             "Show the old image here" is pressed, never by itself on a view of the page -->
        <img v-if="gaps.legacy.showable && showOld && !oldBroken" :src="safeExternalUrl(gaps.legacy.href)"
             :alt="t('orgMarkWhy.legacyAlt', 'Its old logo')" class="omw__old" referrerpolicy="no-referrer"
             data-testid="org-mark-why-legacy-image" @error="oldBroken = true" />
        <div class="omw__legacy">
          <p class="omw__why">{{ tp('orgMarkWhy.legacy', 'It still names an old logo at {host}, which is no longer shown. Save that image, then upload it as its logo.', { host: gaps.legacy.host }) }}</p>
          <p v-if="oldBroken" class="omw__hint" data-testid="org-mark-why-legacy-broken">{{ tp('orgMarkWhy.legacyBroken', 'The old image did not load from {host}.', { host: gaps.legacy.host }) }}</p>
          <div class="omw__acts">
            <button v-if="gaps.legacy.showable && !showOld" type="button" class="omw__btn" data-testid="org-mark-why-legacy-show"
                    @click="showOld = true">{{ t('orgMarkWhy.legacyShow', 'Show the old image here') }}</button>
            <a :href="safeExternalUrl(gaps.legacy.href)" target="_blank" rel="noopener noreferrer" class="omw__link"
               data-testid="org-mark-why-legacy-open">{{ t('orgMarkWhy.legacyOpen', 'Open the old image') }}</a>
          </div>
        </div>
      </li>
    </ul>
    <p class="omw__hint">{{ t('orgMarkWhy.after', 'Once it is listed and has a logo hosted here, its agents\' cards show the logo and name, here at once and on every peer after its next sync.') }}</p>
    <p v-if="error" class="omw__err" data-testid="org-mark-why-error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { organizationService } from '@/services/api/organizationService'
import { logoFileProblem, markShows, missingList, orgMarkGaps } from '@/services/orgMarkWhy'
import { safeExternalUrl } from '@/utils/safeUrl'

const props = withDefaults(defineProps<{
  orgId: string
  listed?: boolean
  /** the logo this registry hosts (a path on this registry), or null */
  logo?: string | null
  /** the address the organization named for its logo before V0657 (b), never shown */
  logoUrl?: string | null
  /** whether the person may change the listing and the logo (the organization's owner or an admin) */
  canFix?: boolean
  /** the upload control here; false where the logo panel beside it carries one (the settings) */
  uploadHere?: boolean
}>(), { listed: false, logo: null, logoUrl: null, canFix: false, uploadHere: true })

/** What the change answered, for the page to show at once (it reads the organization again too) */
const emit = defineEmits<{ (e: 'changed', patch: { listed?: boolean; logo?: string }): void }>()
const { t, tp } = useI18n()
const busy = ref(false)
const error = ref('')
const oldBroken = ref(false)
/** the old image is shown only after the press: until then nothing on the page asks the host logo_url names */
const showOld = ref(false)

const gaps = computed(() => orgMarkGaps({ listed: props.listed, logo: props.logo, logo_url: props.logoUrl }))
const shows = computed(() => markShows(gaps.value))
const missing = computed(() => missingList(gaps.value))
watch(() => props.logoUrl, () => { oldBroken.value = false; showOld.value = false })

async function list() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await organizationService.updateOrgSettings(props.orgId, { public_listing: true })
    emit('changed', { listed: true })
  } catch (e: any) {
    error.value = e?.detail || e?.message || t('orgMarkWhy.listFailed', 'The organization was not listed.')
  } finally {
    busy.value = false
  }
}

async function onFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || busy.value) return
  error.value = ''
  const problem = logoFileProblem(file)
  if (problem === 'tooBig') {
    error.value = t('orgFace.tooBig', 'A logo is at most 256 KB.')
    return
  }
  if (problem === 'wrongType') {
    error.value = t('orgFace.wrongType', 'A logo is a PNG or a JPEG.')
    return
  }
  busy.value = true
  try {
    const res = await organizationService.uploadLogo(props.orgId, file)
    emit('changed', res?.logo ? { logo: res.logo } : {})
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || t('orgFace.failed', 'The logo was not saved.')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
/* Every text reads at least 4.5:1 over this notice on the organization page's #0d1626 (and #141d2d): OrgMarkWhy.test.ts */
.omw { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; margin: 0 0 16px;
  border: 1px solid rgba(251, 191, 36, 0.35); border-radius: 8px; background: rgba(251, 191, 36, 0.06); }
.omw__title { margin: 0; font-size: 12px; font-weight: 600; color: #fbbf24; }
.omw__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.omw__row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.omw__row--legacy { flex-wrap: nowrap; align-items: flex-start; }
.omw__why { margin: 0; min-width: 0; font-size: 12px; line-height: 1.5; color: #cbd5e1; }
/* beside its control in a row, a reason takes the width; inside .omw__legacy (a column) a basis would be its height */
.omw__row > .omw__why { flex: 1 1 320px; }
.omw__hint { margin: 0; font-size: 12px; line-height: 1.5; color: #a3b1c6; }
.omw__btn { flex: 0 0 auto; display: inline-flex; align-items: center; padding: 4px 12px; font-size: 12px; font-weight: 600;
  border: 1px solid rgba(251, 191, 36, 0.55); border-radius: 6px; color: #fde68a; background: rgba(251, 191, 36, 0.1);
  cursor: pointer; }
.omw__btn:hover:not(:disabled) { background-color: rgba(251, 191, 36, 0.18); }
.omw__btn:disabled { opacity: 0.55; cursor: wait; }
.omw__btn:focus-visible, .omw__upload:focus-within { outline: 2px solid #fde68a; outline-offset: 2px; }
/* the file input stays reachable by the keyboard (a display: none input is not): visually hidden, the label is its face */
.omw__upload { position: relative; }
.omw__upload input { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; clip: rect(0 0 0 0); }
.omw__old { flex: 0 0 48px; width: 48px; height: 48px; object-fit: contain; border-radius: 8px;
  background: rgba(148, 163, 184, 0.12); }
.omw__legacy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.omw__acts { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; }
.omw__link { font-size: 12px; color: #67e8f9; text-decoration: underline; width: fit-content; }
.omw__err { margin: 0; font-size: 12px; color: #fca5a5; }
</style>
