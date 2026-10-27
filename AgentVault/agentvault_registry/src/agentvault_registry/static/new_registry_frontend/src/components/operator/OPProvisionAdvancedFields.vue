<template>
  <!--
    §pass66 (2026-05-22) — Path C / Advanced Provisioning Form sub-component.

    Renders the optional Registry Card v0.3 operator-editable subset as a
    set of collapsible sections, alongside the Quick fields in OPAccountTab.
    Emits `update:modelValue` whenever any field changes; parent merges into
    SelfProvisionRequest.card_overrides on submit.

    Design: every section starts COLLAPSED. User opens what they care about,
    fills, leaves the rest alone. The submit-side strips empty values so we
    only POST what the user actually touched — matches Pydantic's behavior
    on optional fields and keeps the OP's validator from rejecting an
    over-permissive payload.

    Reuses the FLARE_ENCIRCLEMENT_VARIANTS / OVERLAYS catalogs from
    `services/api/registryCardAdmin.ts` so the picker stays in sync with
    the operator-side editor.
  -->
  <div class="op-prov-adv">
    <div class="op-prov-adv-eyebrow">
      Registry Card v0.3 overrides
      <span class="op-prov-adv-eyebrow-hint">— optional. Empty sections skip.</span>
    </div>

    <!-- ── Visual identity ──────────────────────────────────────────── -->
    <div class="op-prov-adv-section">
      <button type="button" class="op-prov-adv-toggle" @click="open.visual = !open.visual">
        <span class="op-prov-adv-arrow" :class="{ 'op-prov-adv-arrow--open': open.visual }">▶</span>
        Visual identity
        <span class="op-prov-adv-toggle-hint" v-if="!open.visual">Orb color, halo, theme, flare variants</span>
      </button>
      <div v-if="open.visual" class="op-prov-adv-body">
        <div class="op-prov-adv-row op-prov-adv-row--three">
          <label class="op-prov-adv-label">
            <span>Orb color</span>
            <div class="op-prov-adv-color-row">
              <input type="color" v-model="model.visual.orb_color" class="op-prov-adv-color" />
              <input type="text" v-model="model.visual.orb_color" class="op-prov-adv-color-text"
                     placeholder="#00d2d2" pattern="^#[0-9a-fA-F]{6}$" />
            </div>
          </label>
          <label class="op-prov-adv-label">
            <span>Halo color</span>
            <div class="op-prov-adv-color-row">
              <input type="color" v-model="model.visual.orb_glow_color" class="op-prov-adv-color" />
              <input type="text" v-model="model.visual.orb_glow_color" class="op-prov-adv-color-text"
                     placeholder="#00ffff" pattern="^#[0-9a-fA-F]{6}$" />
            </div>
          </label>
          <label class="op-prov-adv-label">
            <span>Theme</span>
            <select v-model="model.visual.theme" class="op-prov-adv-input">
              <option value="">— default —</option>
              <option value="neural">neural (cyan)</option>
              <option value="sovereign">sovereign (red)</option>
              <option value="custom">custom</option>
            </select>
          </label>
        </div>

        <div class="op-prov-adv-row op-prov-adv-row--three">
          <label class="op-prov-adv-label">
            <span>Pulse speed (Hz)</span>
            <input type="number" v-model.number="model.visual.orb_pulse_speed_hz" step="0.1" min="0.5" max="3.0"
                   class="op-prov-adv-input" placeholder="1.4" />
          </label>
          <label class="op-prov-adv-label">
            <span>Orb size (px)</span>
            <input type="number" v-model.number="model.visual.orb_size_px" min="10" max="24"
                   class="op-prov-adv-input" placeholder="16" />
          </label>
          <label class="op-prov-adv-label op-prov-adv-checkbox">
            <input type="checkbox" v-model="model.visual.halo_enabled" />
            <span>Halo enabled</span>
          </label>
        </div>

        <label class="op-prov-adv-label">
          <span>Flare encirclement variant <span class="op-prov-adv-tiny">(cosmetic, optional)</span></span>
          <select v-model="model.visual.flare_encirclement_variant" class="op-prov-adv-input">
            <option :value="null">— none —</option>
            <option v-for="v in FLARE_ENCIRCLEMENT_VARIANTS" :key="`enc-${v}`" :value="v">{{ v }}</option>
          </select>
        </label>

        <label class="op-prov-adv-label" v-if="model.visual.flare_encirclement_variant">
          <span>Broken-machine overlay <span class="op-prov-adv-tiny">(requires encirclement)</span></span>
          <select v-model="model.visual.flare_encirclement_overlay" class="op-prov-adv-input">
            <option :value="null">— none —</option>
            <option v-for="v in FLARE_ENCIRCLEMENT_OVERLAYS" :key="`ovl-${v}`" :value="v">{{ v }}</option>
          </select>
        </label>
      </div>
    </div>

    <!-- ── Operator persona ──────────────────────────────────────────── -->
    <div class="op-prov-adv-section">
      <button type="button" class="op-prov-adv-toggle" @click="open.operator = !open.operator">
        <span class="op-prov-adv-arrow" :class="{ 'op-prov-adv-arrow--open': open.operator }">▶</span>
        Operator persona
        <span class="op-prov-adv-toggle-hint" v-if="!open.operator">Bio, company, social links, avatar</span>
      </button>
      <div v-if="open.operator" class="op-prov-adv-body">
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Display name</span>
            <input type="text" v-model="model.operator.display_name" class="op-prov-adv-input" maxlength="128" />
          </label>
          <label class="op-prov-adv-label">
            <span>Company</span>
            <input type="text" v-model="model.operator.company" class="op-prov-adv-input" maxlength="256" />
          </label>
        </div>
        <label class="op-prov-adv-label">
          <span>Bio</span>
          <textarea v-model="model.operator.bio" class="op-prov-adv-input op-prov-adv-textarea"
                    rows="3" maxlength="2000" />
        </label>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>URL</span>
            <input type="url" v-model="model.operator.url" class="op-prov-adv-input"
                   placeholder="https://example.com" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>GitHub URL</span>
            <input type="url" v-model="model.operator.github_url" class="op-prov-adv-input"
                   placeholder="https://github.com/you" maxlength="500" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Twitter handle</span>
            <input type="text" v-model="model.operator.twitter_handle" class="op-prov-adv-input"
                   placeholder="@you" maxlength="16" />
          </label>
          <label class="op-prov-adv-label">
            <span>Timezone</span>
            <input type="text" v-model="model.operator.timezone" class="op-prov-adv-input"
                   placeholder="Europe/Berlin" maxlength="64" />
          </label>
        </div>
        <label class="op-prov-adv-label">
          <span>Operator avatar URL</span>
          <input type="url" v-model="model.operator.operator_avatar_url" class="op-prov-adv-input"
                 placeholder="https://media.example.com/me.png" maxlength="500" />
        </label>
        <label class="op-prov-adv-label">
          <span>Successor contact <span class="op-prov-adv-tiny">(bus-factor-1 mitigation)</span></span>
          <input type="text" v-model="model.operator.successor_contact" class="op-prov-adv-input"
                 placeholder="alice@example.com or @alice on matrix" maxlength="500" />
        </label>
      </div>
    </div>

    <!-- ── Description + tags ──────────────────────────────────────── -->
    <div class="op-prov-adv-section">
      <button type="button" class="op-prov-adv-toggle" @click="open.description = !open.description">
        <span class="op-prov-adv-arrow" :class="{ 'op-prov-adv-arrow--open': open.description }">▶</span>
        Description &amp; tags
        <span class="op-prov-adv-toggle-hint" v-if="!open.description">Public-facing summary + discovery tags</span>
      </button>
      <div v-if="open.description" class="op-prov-adv-body">
        <label class="op-prov-adv-label">
          <span>Public description</span>
          <textarea v-model="model.description" class="op-prov-adv-input op-prov-adv-textarea"
                    rows="3" maxlength="2000" placeholder="One-paragraph summary visible on the federation card" />
        </label>
        <label class="op-prov-adv-label">
          <span>Tags <span class="op-prov-adv-tiny">(comma-separated, max 20)</span></span>
          <input type="text" v-model="tagsCsv" class="op-prov-adv-input"
                 placeholder="ai-agents, payments, eu-region" />
        </label>
      </div>
    </div>

    <!-- ── Commitments ──────────────────────────────────────────── -->
    <div class="op-prov-adv-section">
      <button type="button" class="op-prov-adv-toggle" @click="open.commitments = !open.commitments">
        <span class="op-prov-adv-arrow" :class="{ 'op-prov-adv-arrow--open': open.commitments }">▶</span>
        SLA &amp; commitments
        <span class="op-prov-adv-toggle-hint" v-if="!open.commitments">Uptime, support response, GDPR, license</span>
      </button>
      <div v-if="open.commitments" class="op-prov-adv-body">
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Uptime SLA (%)</span>
            <input type="number" v-model.number="model.commitments.uptime_sla_pct" step="0.1" min="0" max="100"
                   class="op-prov-adv-input" placeholder="99.0" />
          </label>
          <label class="op-prov-adv-label">
            <span>Support response (hours)</span>
            <input type="number" v-model.number="model.commitments.support_response_hours" min="1" max="720"
                   class="op-prov-adv-input" placeholder="72" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Incident disclosure SLA (hours)</span>
            <input type="number" v-model.number="model.commitments.incident_disclosure_sla_hours" min="1" max="720"
                   class="op-prov-adv-input" placeholder="72" />
          </label>
          <label class="op-prov-adv-label">
            <span>Deprecation notice (days)</span>
            <input type="number" v-model.number="model.commitments.deprecation_notice_days" min="0" max="365"
                   class="op-prov-adv-input" placeholder="30" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Open-source license</span>
            <input type="text" v-model="model.commitments.open_source_license" class="op-prov-adv-input"
                   placeholder="AGPL-3.0 / MIT / proprietary" maxlength="64" />
          </label>
          <label class="op-prov-adv-label">
            <span>Data residency</span>
            <input type="text" v-model="model.commitments.data_residency" class="op-prov-adv-input"
                   placeholder="EU / US / global" maxlength="32" />
          </label>
        </div>
        <label class="op-prov-adv-label op-prov-adv-checkbox">
          <input type="checkbox" v-model="model.commitments.gdpr_compliant" />
          <span>GDPR compliant (operator self-attest)</span>
        </label>
        <label class="op-prov-adv-label">
          <span>Breach disclosure policy</span>
          <textarea v-model="model.commitments.breach_disclosure_policy"
                    class="op-prov-adv-input op-prov-adv-textarea"
                    rows="2" maxlength="500"
                    placeholder="How quickly + via what channels will you disclose a security breach?" />
        </label>
      </div>
    </div>

    <!-- ── Links ──────────────────────────────────────────── -->
    <div class="op-prov-adv-section">
      <button type="button" class="op-prov-adv-toggle" @click="open.links = !open.links">
        <span class="op-prov-adv-arrow" :class="{ 'op-prov-adv-arrow--open': open.links }">▶</span>
        Public links
        <span class="op-prov-adv-toggle-hint" v-if="!open.links">Whitepaper, docs, status page, community</span>
      </button>
      <div v-if="open.links" class="op-prov-adv-body">
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Whitepaper</span>
            <input type="url" v-model="model.links.whitepaper" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>Docs</span>
            <input type="url" v-model="model.links.docs" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>GitHub source</span>
            <input type="url" v-model="model.links.github_source" class="op-prov-adv-input"
                   placeholder="https://github.com/…" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>Status page</span>
            <input type="url" v-model="model.links.status_page" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Blog</span>
            <input type="url" v-model="model.links.blog" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>RSS feed</span>
            <input type="url" v-model="model.links.rss" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Terms of service</span>
            <input type="url" v-model="model.links.terms_of_service" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>Privacy policy</span>
            <input type="url" v-model="model.links.privacy_policy" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
        </div>
        <div class="op-prov-adv-row op-prov-adv-row--two">
          <label class="op-prov-adv-label">
            <span>Discord</span>
            <input type="url" v-model="model.links.discord" class="op-prov-adv-input"
                   placeholder="https://discord.gg/…" maxlength="500" />
          </label>
          <label class="op-prov-adv-label">
            <span>Support URL</span>
            <input type="url" v-model="model.links.support_url" class="op-prov-adv-input"
                   placeholder="https://" maxlength="500" />
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed, watch } from 'vue'
import {
  FLARE_ENCIRCLEMENT_VARIANTS,
  FLARE_ENCIRCLEMENT_OVERLAYS,
} from '@/services/api/registryCardAdmin'
import type { RegistryCardOverrides } from '@/services/api/provisioning'

const emit = defineEmits<{
  (e: 'update:modelValue', value: RegistryCardOverrides): void
}>()

// One reactive block holding all field state. Parent reads via the emit.
const model = reactive<{
  description: string
  visual: NonNullable<RegistryCardOverrides['visual']>
  operator: NonNullable<RegistryCardOverrides['operator']>
  commitments: NonNullable<RegistryCardOverrides['commitments']>
  links: NonNullable<RegistryCardOverrides['links']>
}>({
  description: '',
  visual: {
    orb_color: '',
    orb_glow_color: '',
    orb_pulse_speed_hz: undefined,
    orb_size_px: undefined,
    halo_enabled: undefined,
    theme: undefined,
    flare_encirclement_variant: null,
    flare_encirclement_overlay: null,
  } as any,
  operator: {} as any,
  commitments: {} as any,
  links: {} as any,
})

const tagsCsv = ref<string>('')

// Section collapse state — all closed by default. User opens what they want.
const open = reactive({
  visual: false,
  operator: false,
  description: false,
  commitments: false,
  links: false,
})

// Strip empties → keep payload minimal. Pydantic on the OP side accepts
// partial RegistryCardOperatorPut so this is safe.
function _stripEmpty<T extends Record<string, any>>(obj: T): Partial<T> {
  const out: any = {}
  for (const k of Object.keys(obj)) {
    const v = obj[k]
    if (v === undefined || v === null) continue
    if (typeof v === 'string' && v.trim() === '') continue
    if (Array.isArray(v) && v.length === 0) continue
    if (typeof v === 'object' && !Array.isArray(v)) {
      const nested = _stripEmpty(v)
      if (Object.keys(nested).length > 0) out[k] = nested
    } else {
      out[k] = v
    }
  }
  return out
}

const composed = computed<RegistryCardOverrides>(() => {
  const tags = tagsCsv.value
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)
    .slice(0, 20)
  const payload: RegistryCardOverrides = {}
  if (model.description.trim()) payload.description = model.description.trim()
  if (tags.length) payload.tags = tags
  const visual = _stripEmpty(model.visual)
  if (Object.keys(visual).length) payload.visual = visual as any
  const operator = _stripEmpty(model.operator)
  if (Object.keys(operator).length) payload.operator = operator as any
  const commitments = _stripEmpty(model.commitments)
  if (Object.keys(commitments).length) payload.commitments = commitments as any
  const links = _stripEmpty(model.links)
  if (Object.keys(links).length) payload.links = links as any
  return payload
})

watch(composed, (v) => emit('update:modelValue', v), { deep: true, immediate: true })

// Reset hook — parent can call via ref + exposed method
function reset() {
  model.description = ''
  Object.keys(model.visual).forEach(k => ((model.visual as any)[k] = k.endsWith('_variant') || k.endsWith('_overlay') ? null : undefined))
  Object.keys(model.operator).forEach(k => ((model.operator as any)[k] = undefined))
  Object.keys(model.commitments).forEach(k => ((model.commitments as any)[k] = undefined))
  Object.keys(model.links).forEach(k => ((model.links as any)[k] = undefined))
  tagsCsv.value = ''
  open.visual = open.operator = open.description = open.commitments = open.links = false
}

defineExpose({ reset })
</script>

<style scoped>
.op-prov-adv {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 1rem;
  border: 1px solid var(--nc-border, rgba(0, 210, 210, 0.16));
  border-radius: 8px;
  background: var(--nc-surface-alt, rgba(255, 255, 255, 0.02));
}

.op-prov-adv-eyebrow {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--nc-primary, #00d2d2);
  font-weight: 600;
  padding-bottom: 0.5rem;
}

.op-prov-adv-eyebrow-hint {
  text-transform: none;
  letter-spacing: normal;
  color: var(--nc-text-dim, rgba(255, 255, 255, 0.45));
  font-weight: 400;
  margin-left: 0.25rem;
}

.op-prov-adv-section {
  border-top: 1px solid var(--nc-border, rgba(255, 255, 255, 0.06));
  padding-top: 0.5rem;
}

.op-prov-adv-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.5rem 0;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.9rem;
  color: var(--nc-text, #e8f1ff);
  text-align: left;
}

.op-prov-adv-toggle:hover {
  color: var(--nc-primary, #00d2d2);
}

.op-prov-adv-arrow {
  display: inline-block;
  transition: transform 0.18s ease;
  color: var(--nc-text-dim, rgba(255, 255, 255, 0.45));
  font-size: 0.6rem;
  min-width: 8px;
}

.op-prov-adv-arrow--open {
  transform: rotate(90deg);
}

.op-prov-adv-toggle-hint {
  color: var(--nc-text-dim, rgba(255, 255, 255, 0.45));
  font-size: 0.8rem;
  margin-left: auto;
  font-weight: 400;
}

.op-prov-adv-body {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.5rem 0 1rem 1rem;
}

.op-prov-adv-row {
  display: grid;
  gap: 0.75rem;
}

.op-prov-adv-row--two {
  grid-template-columns: 1fr 1fr;
}

.op-prov-adv-row--three {
  grid-template-columns: 1fr 1fr 1fr;
}

@media (max-width: 760px) {
  .op-prov-adv-row--two,
  .op-prov-adv-row--three {
    grid-template-columns: 1fr;
  }
}

.op-prov-adv-label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.85rem;
  color: var(--nc-text, #e8f1ff);
}

.op-prov-adv-label > span {
  font-size: 0.78rem;
  color: var(--nc-text-dim, rgba(255, 255, 255, 0.7));
}

.op-prov-adv-tiny {
  font-size: 0.7rem;
  color: var(--nc-text-dim, rgba(255, 255, 255, 0.45));
}

.op-prov-adv-input {
  width: 100%;
  padding: 0.5rem 0.65rem;
  background: var(--nc-surface, rgba(0, 0, 0, 0.35));
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.08));
  border-radius: 6px;
  color: var(--nc-text, #e8f1ff);
  font-size: 0.9rem;
  font-family: inherit;
}

.op-prov-adv-input:focus {
  outline: none;
  border-color: var(--nc-primary, #00d2d2);
}

.op-prov-adv-textarea {
  resize: vertical;
  min-height: 60px;
}

.op-prov-adv-checkbox {
  flex-direction: row;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.op-prov-adv-checkbox > span {
  font-size: 0.85rem;
  color: var(--nc-text, #e8f1ff);
}

.op-prov-adv-color-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.op-prov-adv-color {
  width: 36px;
  height: 36px;
  padding: 0;
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.08));
  border-radius: 6px;
  cursor: pointer;
  background: none;
}

.op-prov-adv-color-text {
  flex: 1;
  padding: 0.5rem 0.65rem;
  background: var(--nc-surface, rgba(0, 0, 0, 0.35));
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.08));
  border-radius: 6px;
  color: var(--nc-text, #e8f1ff);
  font-size: 0.85rem;
  font-family: var(--nc-mono, ui-monospace, monospace);
}
</style>
