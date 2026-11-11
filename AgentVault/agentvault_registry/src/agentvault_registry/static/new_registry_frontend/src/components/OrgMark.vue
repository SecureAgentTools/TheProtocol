<template>
  <!-- V0657 (b), items 4 and 5: an agent's organization as its home registry states it (services/orgMark.ts).
       One component for every place an agent shows (the shared agent modal, the discovery cards, the chat header). -->
  <component
    :is="link?.kind === 'route' ? 'RouterLink' : link?.kind === 'external' ? 'a' : 'span'"
    v-if="mark"
    class="om"
    :class="[`om--${size}`, { 'om--link': !!link }]"
    data-testid="org-mark"
    :data-org="mark.slug || mark.id"
    :to="link?.kind === 'route' ? link.to : undefined"
    :href="link?.kind === 'external' ? safeExternalUrl(link.href) : undefined"
    :target="link?.kind === 'external' ? '_blank' : undefined"
    :rel="link?.kind === 'external' ? 'noopener noreferrer' : undefined"
    :title="title"
    @click.stop
  >
    <img v-if="logo && !broken" :src="logo" alt="" class="om__logo" loading="lazy" referrerpolicy="no-referrer"
         @error="broken = true" />
    <span v-else class="om__glyph" aria-hidden="true">
      <svg viewBox="0 0 14 14" width="11" height="11"><path d="M2 12 L2 5 L7 2 L12 5 L12 12 Z M5 12 L5 8.5 L9 8.5 L9 12"
        stroke="currentColor" stroke-width="1.2" fill="none" stroke-linejoin="round" /></svg>
    </span>
    <span class="om__name">{{ mark.name }}</span>
    <!-- session-lead's review (room seq 1608): a mark from another registry names its home VISIBLY (a title never shows
         on a phone). Organizations are local, so a peer can list one with our name and logo; the home tells them apart.
         The separator is decoration and stays out of the accessible name. -->
    <template v-if="homeShown">
      <span class="om__sep" aria-hidden="true">·</span>
      <span class="om__home" data-testid="org-mark-home">{{ homeShown }}</span>
    </template>
  </component>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { orgMarkLink, safeLogo, type OrgMark } from '@/services/orgMark'
import { safeExternalUrl } from '@/utils/safeUrl'

const props = withDefaults(defineProps<{
  mark: OrgMark | null | undefined
  /** the agent is of this registry (its organization's page is on this console) */
  local?: boolean
  size?: 'sm' | 'md'
  /** the registry this console knows the agent came from (a mirror's source); else the mark's own home */
  homeName?: string | null
}>(), { local: false, size: 'sm', homeName: null })

const { tp } = useI18n()
const broken = ref(false)
watch(() => props.mark?.logo, () => { broken.value = false })
const logo = computed(() => safeLogo(props.mark))
const link = computed(() => orgMarkLink(props.mark, props.local))
/** the home, shown beside the name for a mark that is not this registry's */
// (the discovery mapper names an unknown source 'Federated', a placeholder rather than a registry: the mark's home then)
const homeShown = computed(() => {
  if (props.local || !props.mark) return ''
  const known = props.homeName && props.homeName !== 'Federated' ? props.homeName : ''
  return (known || props.mark.home?.name || '').trim()
})
const title = computed(() => props.mark
  ? tp('orgMark.title', 'Organization {name}, stated by its home registry {home}',
    { name: props.mark.name, home: props.mark.home?.name || '' })
  : '')
</script>

<style scoped>
.om { display: inline-flex; align-items: center; gap: 5px; max-width: 100%; min-width: 0; color: inherit;
  text-decoration: none; border: 1px solid rgba(148, 163, 184, .28); border-radius: 999px; padding: 1px 8px 1px 2px; }
.om--link:hover { border-color: rgba(34, 211, 238, .6); }
.om__logo, .om__glyph { flex: 0 0 auto; width: 16px; height: 16px; border-radius: 50%; object-fit: cover;
  display: inline-flex; align-items: center; justify-content: center; background: rgba(148, 163, 184, .14); }
.om--md .om__logo, .om--md .om__glyph { width: 20px; height: 20px; }
.om__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.om__sep { opacity: .5; font-size: 11px; }
.om__home { flex: 0 0 auto; font-size: 10px; letter-spacing: .04em; text-transform: uppercase; opacity: .75; }
.om--md .om__name { font-size: 13px; }
</style>
