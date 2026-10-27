<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * ThemeStudio.vue — Brand theme picker (Build #15, 2026-05-08).
 *
 * Lets the operator pick a primary color and persists it as their custom
 * brand theme. Two built-in presets (Neural cyan, Sovereign red) plus one
 * user-defined custom slot.
 *
 * Pickers:
 *  - 2D saturation×lightness pad (the colored square the user drags on)
 *  - Hue rainbow slider underneath
 *  - Hex text input
 *  - 8 quick-pick swatches
 *
 * Live preview shows the four derived variants (primary/bright/dim/dark)
 * + a glow chip + a subtle chip + a sample button + a sample card,
 * so the operator sees exactly how the theme will land before committing.
 *
 * Apply & Save = persist + activate. Forget = remove custom + revert to neural.
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useUIStore, themeMath, type BrandTheme } from '@/stores/ui'

const ui = useUIStore()

// ── Edit state ─────────────────────────────────────────────────────────────
// editHex is the CANONICAL source of truth. Sliders/pad mutate it through
// commitHsl() which computes a fresh hex; quick-swatch/hex-input mutate it
// directly and call syncDisplayHsl() to update slider/pad indicators.
// This keeps swatch picks pixel-exact (no hex→HSL→hex round-trip drift).
const editHex = ref<string>('#00D2D2')
// _hue/_sat/_lit drive the slider + pad UI. Display-only — never the source
// of truth. Updated when editHex changes via syncDisplayHsl(); sliders/pad
// write into them and then call commitHsl() to push hex.
const _hue = ref(180)
const _sat = ref(100)
const _lit = ref(50)
const editing = ref(false)       // shows the picker section
const validHex = computed(() => /^#[0-9A-Fa-f]{6}$/.test(editHex.value))

// Quick-pick swatches: name + hex
const QUICK_SWATCHES: { name: string; hex: string }[] = [
  { name: 'Cyan',    hex: '#00D2D2' },
  { name: 'Red',     hex: '#DC2626' },
  { name: 'Violet',  hex: '#8B5CF6' },
  { name: 'Emerald', hex: '#10B981' },
  { name: 'Amber',   hex: '#F59E0B' },
  { name: 'Rose',    hex: '#F43F5E' },
  { name: 'Sky',     hex: '#0EA5E9' },
  { name: 'Gold',    hex: '#EAB308' },
]

// ── Hex / HSL sync (one direction only per call — no watchers, no loops) ───
/** Push current display HSL → editHex (slider/pad path). */
function commitHsl() {
  editHex.value = themeMath.hslToHex(_hue.value, _sat.value, _lit.value)
}
/** Pull editHex → display HSL (swatch/hex-input path). */
function syncDisplayHsl() {
  if (!themeMath.parseHex(editHex.value)) return
  const [h, s, l] = themeMath.hexToHsl(editHex.value)
  _hue.value = Math.round(h)
  _sat.value = Math.round(s)
  _lit.value = Math.round(l)
}

// ── Derived preview variants ────────────────────────────────────────────────
const previewVariants = computed(() => {
  if (!validHex.value) return null
  return themeMath.deriveVariants(editHex.value)
})

// ── Picker pad geometry ─────────────────────────────────────────────────────
// The 2D pad maps:  x → saturation 0-100,  y → lightness (top brightest).
// Display-mapping: top row ≈ pure-hue tint (l 100 at s 0, l 50 at s 100);
// bottom row darkens via overlay. We use a simple linear mapping where
// y = 0 → l 50 (pure hue), y = 100% → l 0 (black overlay).
const padHandlePos = computed(() => ({
  left: `${_sat.value}%`,
  top:  `${100 - _lit.value * 2}%`,
}))

let padDragging = false
function onPadPointerDown(e: PointerEvent) {
  padDragging = true
  ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
  updatePadFromEvent(e)
}
function onPadPointerMove(e: PointerEvent) {
  if (!padDragging) return
  updatePadFromEvent(e)
}
function onPadPointerUp(e: PointerEvent) {
  padDragging = false
  ;(e.currentTarget as Element).releasePointerCapture(e.pointerId)
}
function updatePadFromEvent(e: PointerEvent) {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const x = Math.max(0, Math.min(rect.width, e.clientX - rect.left))
  const y = Math.max(0, Math.min(rect.height, e.clientY - rect.top))
  _sat.value = Math.round((x / rect.width) * 100)
  _lit.value = Math.round(50 - (y / rect.height) * 50)
  commitHsl()
}

// Slider input handlers (explicit — no watchers, no loops).
function onHueInput()  { commitHsl() }
function onSatInput()  { commitHsl() }
function onLitInput()  { commitHsl() }

// ── Apply & Save ────────────────────────────────────────────────────────────
function applyAndSave() {
  if (!validHex.value) return
  const ok = ui.setCustomThemeHex(editHex.value)
  if (!ok) return
  ui.setBrandTheme('custom')
  editing.value = false
  ui.showSuccess('Theme saved', `Custom palette applied: ${editHex.value}`)
}

function startEditingFromHex(hex: string) {
  editHex.value = hex.toUpperCase()
  syncDisplayHsl()
  editing.value = true
}

function startEditing() {
  // Seed from current custom (or neural cyan as a safe default)
  editHex.value = (ui.customThemeHex || '#00D2D2').toUpperCase()
  syncDisplayHsl()
  editing.value = true
}

function cancelEditing() {
  editing.value = false
}

function pickPreset(theme: BrandTheme) {
  ui.setBrandTheme(theme)
}

function forgetCustom() {
  ui.clearCustomTheme()
  editing.value = false
  ui.showInfo('Custom theme cleared', 'Reverted to Neural.')
}

// Hex input with hash autoinsert. Sync display HSL only when valid.
function onHexInput(v: string) {
  let s = v.trim()
  if (s && !s.startsWith('#')) s = '#' + s
  s = s.toUpperCase()
  editHex.value = s.slice(0, 7)
  if (themeMath.parseHex(editHex.value)) syncDisplayHsl()
}

// ── Lifecycle ───────────────────────────────────────────────────────────────
onMounted(() => {
  // Seed editor from current custom (so opening the picker shows their work).
  editHex.value = (ui.customThemeHex || '#00D2D2').toUpperCase()
  syncDisplayHsl()
})
onBeforeUnmount(() => {
  padDragging = false
})

// Display helpers
function presetActive(t: BrandTheme): boolean {
  return ui.brandTheme === t
}
const NEURAL_PREVIEW = '#00D2D2'
const SOVEREIGN_PREVIEW = '#DC2626'
</script>

<template>
  <div class="ts">
    <div class="ts-card-title">
      <span class="ts-card-icon"><Icon name="mdi:palette-outline" /></span> Brand Theme
      <span class="ts-active-pill" :title="`Currently active: ${ui.brandTheme}`">
        <span class="ts-active-dot" :style="{
          background: ui.brandTheme === 'neural'    ? NEURAL_PREVIEW
                   : ui.brandTheme === 'sovereign' ? SOVEREIGN_PREVIEW
                   : (ui.customThemeHex || NEURAL_PREVIEW)
        }" />
        {{ ui.brandTheme }}
      </span>
    </div>
    <p class="ts-hint">
      Pick the accent color used across the app. Two presets ship with the
      registry; the third slot is yours — pick any color from the spectrum or
      type a hex code, then save it locally to this browser.
    </p>

    <!-- Preset card row -->
    <div class="ts-preset-grid">
      <!-- NEURAL -->
      <button
        type="button"
        class="ts-preset"
        :class="{ active: presetActive('neural') }"
        @click="pickPreset('neural')"
        :title="`Neural (cyan ${NEURAL_PREVIEW})`"
      >
        <div class="ts-preset-swatch" :style="{ background: NEURAL_PREVIEW }">
          <div class="ts-preset-shine" />
        </div>
        <div class="ts-preset-label">Neural</div>
        <div class="ts-preset-sub">Cyan · {{ NEURAL_PREVIEW }}</div>
        <div v-if="presetActive('neural')" class="ts-preset-active">ACTIVE</div>
      </button>

      <!-- SOVEREIGN -->
      <button
        type="button"
        class="ts-preset"
        :class="{ active: presetActive('sovereign') }"
        @click="pickPreset('sovereign')"
        :title="`Sovereign (red ${SOVEREIGN_PREVIEW})`"
      >
        <div class="ts-preset-swatch" :style="{ background: SOVEREIGN_PREVIEW }">
          <div class="ts-preset-shine" />
        </div>
        <div class="ts-preset-label">Sovereign</div>
        <div class="ts-preset-sub">Red · {{ SOVEREIGN_PREVIEW }}</div>
        <div v-if="presetActive('sovereign')" class="ts-preset-active">ACTIVE</div>
      </button>

      <!-- CUSTOM -->
      <button
        type="button"
        class="ts-preset ts-preset--custom"
        :class="{ active: presetActive('custom'), defined: !!ui.customThemeHex }"
        @click="ui.customThemeHex ? pickPreset('custom') : startEditing()"
        :title="ui.customThemeHex ? `Custom (${ui.customThemeHex})` : 'Custom — pick your own color'"
      >
        <div class="ts-preset-swatch" :style="{
          background: ui.customThemeHex ?? 'conic-gradient(from 0deg, #ff0080, #ff8c00, #ffd000, #00ff80, #00d2d2, #6366f1, #ff0080)'
        }">
          <div v-if="ui.customThemeHex" class="ts-preset-shine" />
          <div v-else class="ts-preset-question">?</div>
        </div>
        <div class="ts-preset-label">Custom</div>
        <div class="ts-preset-sub">
          <template v-if="ui.customThemeHex">{{ ui.customThemeHex }}</template>
          <template v-else>Pick your own</template>
        </div>
        <div v-if="presetActive('custom')" class="ts-preset-active">ACTIVE</div>
      </button>
    </div>

    <!-- Action row: edit / forget custom -->
    <div class="ts-actions">
      <button
        v-if="!editing"
        type="button"
        class="ts-btn ts-btn--primary"
        @click="ui.customThemeHex ? startEditingFromHex(ui.customThemeHex) : startEditing()"
      >
        <span class="ts-btn-icon"><Icon name="mdi:palette-outline" /></span>
        {{ ui.customThemeHex ? 'Edit custom theme' : 'Create custom theme' }}
      </button>
      <button
        v-if="!editing && ui.customThemeHex"
        type="button"
        class="ts-btn ts-btn--ghost"
        @click="forgetCustom"
        title="Remove the saved custom palette and revert to Neural"
      >
        Forget custom
      </button>
    </div>

    <!-- ═══════════════ THE PICKER ═══════════════ -->
    <div v-if="editing" class="ts-picker">
      <div class="ts-picker-grid">

        <!-- Left column: 2D pad + hue slider -->
        <div class="ts-picker-left">
          <!-- 2D saturation × lightness pad -->
          <div
            class="ts-pad"
            :style="{ '--pad-hue': _hue }"
            @pointerdown="onPadPointerDown"
            @pointermove="onPadPointerMove"
            @pointerup="onPadPointerUp"
            @pointercancel="onPadPointerUp"
          >
            <div class="ts-pad-overlay-1" />
            <div class="ts-pad-overlay-2" />
            <div class="ts-pad-handle" :style="padHandlePos" />
          </div>

          <!-- Hue rainbow slider -->
          <div class="ts-hue-wrap">
            <input
              type="range"
              class="ts-hue-slider"
              min="0"
              max="360"
              step="1"
              v-model.number="_hue"
              @input="onHueInput"
              :title="`Hue: ${_hue}°`"
              aria-label="Hue"
            />
          </div>
        </div>

        <!-- Right column: hex input, HSL sliders, swatches, preview -->
        <div class="ts-picker-right">
          <!-- Hex input -->
          <label class="ts-field">
            <span class="ts-field-label">Hex</span>
            <input
              type="text"
              class="ts-field-input"
              :value="editHex"
              @input="onHexInput(($event.target as HTMLInputElement).value)"
              @blur="validHex && syncDisplayHsl()"
              maxlength="7"
              placeholder="#RRGGBB"
              spellcheck="false"
              aria-label="Hex color code"
            />
            <span v-if="!validHex" class="ts-field-warn">Invalid hex</span>
          </label>

          <!-- Saturation slider -->
          <label class="ts-field">
            <span class="ts-field-label">Sat <span class="ts-field-num">{{ _sat }}%</span></span>
            <input
              type="range"
              class="ts-range"
              min="0"
              max="100"
              v-model.number="_sat"
              @input="onSatInput"
              aria-label="Saturation"
            />
          </label>

          <!-- Lightness slider -->
          <label class="ts-field">
            <span class="ts-field-label">Light <span class="ts-field-num">{{ _lit }}%</span></span>
            <input
              type="range"
              class="ts-range"
              min="0"
              max="100"
              v-model.number="_lit"
              @input="onLitInput"
              aria-label="Lightness"
            />
          </label>

          <!-- Quick swatches -->
          <div class="ts-swatch-row" role="group" aria-label="Quick color presets">
            <button
              v-for="s in QUICK_SWATCHES"
              :key="s.hex"
              type="button"
              class="ts-swatch"
              :class="{ active: editHex.toUpperCase() === s.hex.toUpperCase() }"
              :style="{ background: s.hex }"
              @click="editHex = s.hex; syncDisplayHsl()"
              :title="`${s.name} (${s.hex})`"
              :aria-label="`Pick ${s.name}`"
            />
          </div>

          <!-- Live preview (only when valid) -->
          <div v-if="previewVariants" class="ts-preview">
            <div class="ts-preview-label">PREVIEW</div>
            <div class="ts-preview-row">
              <div class="ts-preview-chip" :style="{ background: previewVariants.primary }" title="primary">
                <span>primary</span>
              </div>
              <div class="ts-preview-chip" :style="{ background: previewVariants.bright }" title="bright (hover)">
                <span>bright</span>
              </div>
              <div class="ts-preview-chip" :style="{ background: previewVariants.dim }" title="dim (active)">
                <span>dim</span>
              </div>
              <div class="ts-preview-chip" :style="{ background: previewVariants.dark }" title="dark (disabled)">
                <span>dark</span>
              </div>
            </div>
            <div class="ts-preview-row">
              <div
                class="ts-preview-glow"
                :style="{ background: `rgba(${previewVariants.primaryRgb}, 0.1)`, borderColor: previewVariants.primary, color: previewVariants.primary }"
                title="subtle 0.1α + primary border"
              >
                Sample button
              </div>
              <div
                class="ts-preview-card"
                :style="{ background: `rgba(${previewVariants.primaryRgb}, 0.06)`, borderColor: `rgba(${previewVariants.primaryRgb}, 0.4)`, boxShadow: `0 0 12px rgba(${previewVariants.primaryRgb}, 0.3)` }"
              >
                <span :style="{ color: previewVariants.bright }">●●●</span>
                <span class="ts-preview-card-text">Card preview</span>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- Apply / cancel -->
      <div class="ts-picker-foot">
        <button
          type="button"
          class="ts-btn ts-btn--primary ts-btn--xl"
          :disabled="!validHex"
          @click="applyAndSave"
        >
          ✓ Apply &amp; activate
        </button>
        <button type="button" class="ts-btn ts-btn--ghost" @click="cancelEditing">Cancel</button>
        <span class="ts-picker-foot-hint">
          Stored locally in this browser only · sovereign isolation respected.
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Theme tokens — alias view-locally so theme cycle (incl. custom) carries here. */
.ts {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  display: block;
}
.ts-card-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--cyan);
  margin-bottom: 8px;
}
.ts-active-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  padding: 3px 10px;
  background: rgba(var(--cyan-rgb), 0.12);
  border: 1px solid rgba(var(--cyan-rgb), 0.4);
  border-radius: 100px;
  font-size: 10px;
  letter-spacing: 1.2px;
  color: var(--cyan);
  text-transform: uppercase;
}
.ts-active-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 0 8px currentColor;
}
.ts-hint {
  color: rgba(255, 255, 255, 0.55);
  font-size: 12px;
  line-height: 1.6;
  margin: 0 0 18px 0;
}

/* ── Preset grid ─────────────────────────────────────────────────────────── */
.ts-preset-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}
.ts-preset {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px 12px 14px 12px;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  cursor: pointer;
  transition: all 200ms ease;
  font-family: inherit;
  color: inherit;
}
.ts-preset:hover {
  border-color: rgba(var(--cyan-rgb), 0.4);
  background: rgba(0, 0, 0, 0.5);
  transform: translateY(-1px);
}
.ts-preset.active {
  border-color: var(--cyan);
  background: rgba(var(--cyan-rgb), 0.08);
  box-shadow: 0 0 18px rgba(var(--cyan-rgb), 0.3), inset 0 0 12px rgba(var(--cyan-rgb), 0.05);
}
.ts-preset-swatch {
  position: relative;
  width: 64px;
  height: 64px;
  border-radius: 12px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4), inset 0 0 0 1px rgba(255, 255, 255, 0.18);
  overflow: hidden;
}
.ts-preset-shine {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 30% 30%, rgba(255, 255, 255, 0.4), transparent 60%);
  pointer-events: none;
}
.ts-preset-question {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: rgba(0, 0, 0, 0.7);
  font-size: 28px;
  font-weight: 800;
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.5);
}
.ts-preset-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.95);
}
.ts-preset-sub {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  letter-spacing: 0.5px;
}
.ts-preset-active {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 1.2px;
  padding: 2px 6px;
  background: var(--cyan);
  color: #000;
  border-radius: 3px;
}

/* ── Action row ──────────────────────────────────────────────────────────── */
.ts-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.ts-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border-radius: 8px;
  font-family: inherit;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 150ms ease;
  border: 1px solid;
}
.ts-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ts-btn--primary {
  background: var(--cyan);
  border-color: var(--cyan);
  color: #000;
}
.ts-btn--primary:hover:not(:disabled) {
  background: var(--nc-primary-bright, #00e5e5);
  box-shadow: 0 0 16px rgba(var(--cyan-rgb), 0.6);
}
.ts-btn--ghost {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.75);
}
.ts-btn--ghost:hover {
  border-color: rgba(255, 255, 255, 0.45);
  color: rgba(255, 255, 255, 1);
}
.ts-btn--xl {
  padding: 12px 22px;
  font-size: 12px;
}
.ts-btn-icon { font-size: 14px; }

/* ── The picker ──────────────────────────────────────────────────────────── */
.ts-picker {
  margin-top: 6px;
  padding: 18px;
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.04), rgba(0, 0, 0, 0.4));
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 12px;
  box-shadow: inset 0 0 18px rgba(var(--cyan-rgb), 0.04);
}
.ts-picker-grid {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 22px;
}
.ts-picker-left {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 2D pad */
.ts-pad {
  position: relative;
  width: 280px;
  height: 220px;
  border-radius: 8px;
  background: hsl(var(--pad-hue, 180), 100%, 50%);
  cursor: crosshair;
  overflow: hidden;
  touch-action: none;
  user-select: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.ts-pad-overlay-1 {
  position: absolute; inset: 0;
  background: linear-gradient(to right, white, transparent);
  pointer-events: none;
}
.ts-pad-overlay-2 {
  position: absolute; inset: 0;
  background: linear-gradient(to top, black, transparent);
  pointer-events: none;
}
.ts-pad-handle {
  position: absolute;
  width: 14px; height: 14px;
  border-radius: 50%;
  border: 2px solid white;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.6), 0 2px 6px rgba(0, 0, 0, 0.5);
  transform: translate(-50%, -50%);
  pointer-events: none;
  background: transparent;
}

/* Hue slider — rainbow gradient */
.ts-hue-wrap {
  width: 280px;
}
.ts-hue-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 18px;
  border-radius: 4px;
  background: linear-gradient(to right,
    hsl(0, 100%, 50%),
    hsl(60, 100%, 50%),
    hsl(120, 100%, 50%),
    hsl(180, 100%, 50%),
    hsl(240, 100%, 50%),
    hsl(300, 100%, 50%),
    hsl(360, 100%, 50%));
  outline: none;
  border: 1px solid rgba(255, 255, 255, 0.1);
  cursor: pointer;
}
.ts-hue-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 22px;
  border-radius: 3px;
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.5);
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
  cursor: pointer;
}
.ts-hue-slider::-moz-range-thumb {
  width: 12px;
  height: 22px;
  border-radius: 3px;
  background: white;
  border: 1px solid rgba(0, 0, 0, 0.5);
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
  cursor: pointer;
}

.ts-picker-right {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* ── Form fields ─────────────────────────────────────────────────────────── */
.ts-field {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ts-field-label {
  flex: 0 0 56px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.ts-field-num {
  font-size: 9px;
  color: var(--cyan);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0;
  text-transform: none;
}
.ts-field-input {
  flex: 1;
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 6px;
  padding: 8px 12px;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  letter-spacing: 0.8px;
  outline: none;
  transition: border-color 150ms;
}
.ts-field-input:focus {
  border-color: var(--cyan);
  box-shadow: 0 0 0 2px rgba(var(--cyan-rgb), 0.18);
}
.ts-field-warn {
  font-size: 10px;
  color: #f87171;
  font-weight: 600;
}
.ts-range {
  -webkit-appearance: none;
  appearance: none;
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: linear-gradient(to right, rgba(var(--cyan-rgb), 0.15), rgba(var(--cyan-rgb), 0.55));
  outline: none;
  border: 1px solid rgba(255, 255, 255, 0.05);
  cursor: pointer;
}
.ts-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  border: 2px solid var(--cyan);
  box-shadow: 0 0 4px rgba(var(--cyan-rgb), 0.5);
  cursor: pointer;
}
.ts-range::-moz-range-thumb {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: white;
  border: 2px solid var(--cyan);
  cursor: pointer;
}

/* ── Quick swatches ──────────────────────────────────────────────────────── */
.ts-swatch-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.ts-swatch {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.15);
  cursor: pointer;
  transition: all 150ms ease;
  position: relative;
  padding: 0;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.4), 0 2px 4px rgba(0, 0, 0, 0.3);
}
.ts-swatch:hover {
  transform: translateY(-2px) scale(1.06);
  box-shadow: 0 0 10px rgba(255, 255, 255, 0.4);
}
.ts-swatch.active {
  border-color: white;
  box-shadow: 0 0 0 2px white, 0 0 12px rgba(255, 255, 255, 0.6);
}

/* ── Live preview ────────────────────────────────────────────────────────── */
.ts-preview {
  margin-top: 8px;
  padding: 12px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
  border: 1px dashed rgba(255, 255, 255, 0.15);
}
.ts-preview-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  color: rgba(255, 255, 255, 0.45);
  margin-bottom: 8px;
}
.ts-preview-row {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.ts-preview-row:last-child { margin-bottom: 0; }
.ts-preview-chip {
  flex: 1;
  padding: 12px 8px;
  border-radius: 6px;
  text-align: center;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: rgba(0, 0, 0, 0.85);
  font-family: 'JetBrains Mono', monospace;
  border: 1px solid rgba(255, 255, 255, 0.15);
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.4);
}
.ts-preview-glow {
  flex: 1;
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid;
  text-align: center;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  cursor: default;
}
.ts-preview-card {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid;
  border-radius: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.85);
}
.ts-preview-card-text {
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.5px;
}

/* ── Foot ────────────────────────────────────────────────────────────────── */
.ts-picker-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.ts-picker-foot-hint {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.4);
  margin-left: auto;
}

/* Responsive */
@media (max-width: 760px) {
  .ts-picker-grid {
    grid-template-columns: 1fr;
  }
  .ts-pad {
    width: 100%;
  }
  .ts-hue-wrap {
    width: 100%;
  }
  .ts-preset-grid {
    grid-template-columns: 1fr;
  }
}
</style>
