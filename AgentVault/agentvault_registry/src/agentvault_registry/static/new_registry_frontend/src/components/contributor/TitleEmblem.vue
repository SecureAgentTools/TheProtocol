<!--
  TitleEmblem — the contributor track's TITLES (V0665 art; his idea, room seq 4063/4070/4081; his notes seq 4134: "every title gets a plate").

  A title shows under the name in the sidebar's account block and under the name on the profile card (the two places he marked in
  sessionlogs2026/TempScreenshots/"Screenshot 2026-11-14 211431_dev_title_idea.jpeg"). The text is a translation key.

  ONE PLATE SYSTEM: a slim, chamfered nameplate (a crisp bevel line round a face), in each title's own MATERIAL: steel, brass, blueprint film,
  wax, foil, an LED panel, carbon, smoked glass, paper, iron, bronze. The lettering is small and professional on it (caps, letter-spaced, one
  clean face) and readable at the sidebar size (lettering 8.5 px). Each title keeps its own touch of motion on its plate (a sweep, a typed
  word, a settling glitch), small enough to sit on a nameplate.

  Cheap motion only: opacity and transform, a CSS animation that runs once or loops slowly; a gradient that "flows" is two layers cross-fading
  in opacity, never a moving background. No backdrop-filter, no canvas, no per-frame script. Under prefers-reduced-motion every effect rests in
  a still frame that shows a key moment (the typed half of a word, a shifted slice of a glitch, a sweep midway). The letters are separate
  spans, in words, so an effect can reach one letter (the one slit pupil of The Eye Sees All, the letter that sits a pixel off) and a long
  title wraps between words; the whole text is the element's aria-label.

  Fonts: the console serves IBM Plex Mono and Sans from this origin, and since V0665 IBM Plex Serif Light (latin, public/fonts/fonts.css, its
  copyright line in public/fonts/OFL.txt) for the Senate Scribe plate; Georgia is the fallback.
-->
<template>
  <span class="te" :class="[`te-${titleKey}`, `te-m-${material}`, `te-sz-${size}`, { 'te-still': still, 'te-v-b': variant === 'b' }]" :aria-label="text" role="text" :title="text">
    <span class="te-face">
      <span class="te-t" :data-text="text" aria-hidden="true">
        <template v-for="(w, wi) in words" :key="wi"><span v-if="wi" class="te-sp"> </span><span class="te-w"><span v-for="l in w" :key="l.i" class="te-ch" :class="{ 'te-o': slit(l.c, wi, l.i), 'te-off': l.i === offIndex, 'te-typed': l.i < half }" :style="{ '--i': l.i }">{{ l.c }}</span></span></template>
      </span>
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { TITLE_MATERIAL } from '@/services/contributorTrack'

const props = withDefaults(defineProps<{
  /** one of NEW_TITLES' keys (services/contributorTrack.ts) */
  titleKey: string
  /** sidebar: the tiny line under the name; card: under the name on a profile card; large: for the gallery's close look */
  size?: 'sidebar' | 'card' | 'large'
  still?: boolean
  /** The Eye Sees All has two proposals for his pick: a (the slit pupil in the E of Eye, on the letter) and b (plain words, a small almond eye with a slit pupil as a mark at the plate's left) */
  variant?: 'a' | 'b'
}>(), { size: 'card', still: false, variant: 'a' })

const { t } = useI18n()
const text = computed<string>(() => String(t(`contributorTrack.titles.${props.titleKey}.name`, props.titleKey)))
const material = computed(() => TITLE_MATERIAL[props.titleKey] ?? 'steel')
const letters = computed(() => Array.from(text.value))
// words, so a long title can wrap between words and never inside one; the index (--i) runs over every letter, spaces included
const words = computed(() => {
  const out: { c: string; i: number }[][] = [[]]
  letters.value.forEach((c, i) => { if (c === ' ') out.push([]); else out[out.length - 1].push({ c, i }) })
  return out.filter((w) => w.length)
})
// the letters that take a slit pupil: every O; in The Eye Sees All (which has none) only the E of "Eye" (word 1, its first letter): one eye,
// the other letters plain (session-lead seq 4132); at the sidebar size no letter is replaced at all, only the glow (the stylesheet)
const firstOfWord = (w: number): number => (words.value[w]?.[0]?.i ?? -1)
const slit = (c: string, wordIndex: number, index: number): boolean => {
  if (props.titleKey === 'the-eye-sees-all') return props.variant !== 'b' && wordIndex === 1 && /[eE]/.test(c) && index === firstOfWord(1)
  return /[oO]/.test(c)
}
// Exactly Once: how much of the word the still frame has typed (a half-typed word, the caret after it)
const half = computed(() => Math.ceil(letters.value.length * 0.55))
const offIndex = computed(() => (props.titleKey === 'off-by-one' ? Math.floor(letters.value.length / 2) : -1))
</script>

<style scoped>
/* ═════ the plate system: a chamfered slim nameplate; .te is the bevel (a light edge), .te-face the material inside it ═════ */
.te {
  --fs: 9px;                       /* lettering */
  --g: 2px;                        /* how far a glitch slice is shifted */
  --c: 0.42em;                     /* the chamfer */
  --rim: linear-gradient(180deg, rgba(255, 255, 255, 0.55), rgba(255, 255, 255, 0.08) 45%, rgba(0, 0, 0, 0.55));
  --face: linear-gradient(180deg, #5b6572, #2b323b);
  --ink: #e8eef4;
  --ink-shadow: 0 1px 0 rgba(0, 0, 0, 0.6);
  display: inline-block;
  position: relative;
  padding: 1px;
  background: var(--rim);
  clip-path: polygon(var(--c) 0, calc(100% - var(--c)) 0, 100% var(--c), 100% calc(100% - var(--c)), calc(100% - var(--c)) 100%, var(--c) 100%, 0 calc(100% - var(--c)), 0 var(--c));
  font-family: 'IBM Plex Sans', 'IBM Plex Mono', system-ui, sans-serif;
  font-size: var(--fs);
  font-weight: 600;
  line-height: 1;
  text-transform: uppercase;
  letter-spacing: 0.2em;
  white-space: nowrap;
  color: var(--ink);
  user-select: none;
  isolation: isolate;
  vertical-align: middle;
}
.te-sz-sidebar { --fs: 8.5px; --g: 1px; }
.te-sz-card { --fs: 11px; }
.te-sz-large { --fs: 22px; white-space: normal; max-width: 100%; }
.te-face {
  position: relative;
  display: block;
  overflow: hidden;
  padding: 0.55em 1.05em 0.5em;
  background: var(--face);
  clip-path: polygon(calc(var(--c) - 1px) 0, calc(100% - var(--c) + 1px) 0, 100% calc(var(--c) - 1px), 100% calc(100% - var(--c) + 1px), calc(100% - var(--c) + 1px) 100%, calc(var(--c) - 1px) 100%, 0 calc(100% - var(--c) + 1px), 0 calc(var(--c) - 1px));
}
.te-t { position: relative; display: inline-block; color: var(--ink); text-shadow: var(--ink-shadow); }
.te-t::before, .te-t::after { white-space: nowrap; }
.te-ch { display: inline-block; }
.te-w { display: inline-block; white-space: nowrap; }
.te-sp { display: inline-block; width: 0.55em; }

/* ═════ the materials ═════ */
.te-m-steel { --rim: linear-gradient(180deg, #f4f8fc, #8c98a6 40%, #1d2329); --face: linear-gradient(180deg, #b4bfca 0%, #a0acb8 48%, #8c99a6 52%, #aab5c0 100%), repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.07) 0 1px, transparent 1px 2px); --ink: #06090d; --ink-shadow: 0 1px 0 rgba(255, 255, 255, 0.35); }
.te-m-brass { --rim: linear-gradient(180deg, #fff1c2, #b98a2c 45%, #4a3208); --face: linear-gradient(180deg, #e8c677 0%, #d6ab4c 48%, #c4983c 52%, #deb85e 100%), repeating-linear-gradient(90deg, rgba(255, 240, 190, 0.1) 0 1px, transparent 1px 2px); --ink: #170d02; --ink-shadow: 0 1px 0 rgba(255, 238, 190, 0.3); }
.te-m-blueprint { --rim: linear-gradient(180deg, #bff3ff, #3a9cc4 50%, #0a2c42); --face: linear-gradient(rgba(120, 220, 255, 0.3) 1px, transparent 1px) 0 0 / 100% 0.5em, linear-gradient(90deg, rgba(120, 220, 255, 0.2) 1px, transparent 1px) 0 0 / 0.5em 100%, #082b44; --ink: #ffffff; --ink-shadow: 0 0 6px rgba(90, 210, 255, 0.7); }
.te-m-wax { --rim: linear-gradient(180deg, #ffb3ad, #b3261e 50%, #4c0a0a); --face: radial-gradient(ellipse at 28% 18%, rgba(255, 170, 160, 0.3), transparent 55%), linear-gradient(180deg, #9c231c, #5f0e0b); --ink: #fff7ef; --ink-shadow: 0 -1px 0 rgba(60, 0, 0, 0.7), 0 1px 0 rgba(255, 170, 150, 0.35); }
.te-m-foil { --rim: linear-gradient(180deg, #ffffff, #b6a7ff 45%, #5a4b9a); --face: linear-gradient(115deg, #ffd1f5, #a9c8ff 28%, #b6ffe2 52%, #fff0a8 76%, #ffd1f5); --ink: #1b1536; --ink-shadow: 0 1px 0 rgba(255, 255, 255, 0.6); }
.te-m-led { --rim: linear-gradient(180deg, #7fe8a2, #1c6b3c 50%, #04180c); --face: radial-gradient(circle at 1px 1px, rgba(120, 255, 160, 0.16) 0.7px, transparent 0.9px) 0 0 / 3px 3px, #051a10; --ink: #86ffa3; --ink-shadow: 0 0 5px rgba(80, 255, 140, 0.6); }
.te-m-carbon { --rim: linear-gradient(180deg, #8a93a0, #3c434c 50%, #0a0c0f); --face: repeating-linear-gradient(45deg, rgba(255, 255, 255, 0.05) 0 2px, transparent 2px 4px), repeating-linear-gradient(-45deg, rgba(0, 0, 0, 0.35) 0 2px, transparent 2px 4px), #12161b; --ink: #eef4f8; --ink-shadow: 0 1px 0 rgba(0, 0, 0, 0.8); }
.te-m-glass { --rim: linear-gradient(180deg, rgba(220, 245, 255, 0.85), rgba(120, 170, 200, 0.3) 50%, rgba(10, 30, 45, 0.8)); --face: linear-gradient(180deg, rgba(120, 175, 205, 0.28), rgba(6, 18, 28, 0.9) 52%), #081420; --ink: #dff1fa; --ink-shadow: 0 1px 0 rgba(0, 0, 0, 0.7); }
.te-m-paper { --rim: linear-gradient(180deg, #fff6dc, #c2a878 50%, #5b4a2c); --face: linear-gradient(180deg, #e9d8b0, #cdb68a); --ink: #3a2c14; --ink-shadow: 0 1px 0 rgba(255, 250, 230, 0.6); }
.te-m-iron { --rim: linear-gradient(180deg, #d6a17a, #5a3a28 50%, #120a06); --face: linear-gradient(180deg, #3a2a24, #1a120f), repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.04) 0 1px, transparent 1px 3px); --ink: #ffcf8a; --ink-shadow: 0 0 6px rgba(255, 110, 30, 0.55); }
.te-m-bronze { --rim: linear-gradient(180deg, #ffe39a, #9a6a1c 48%, #2b1a06); --face: linear-gradient(180deg, #3a2410, #1a0f06); --ink: #ffe3a8; --ink-shadow: 0 0 5px rgba(255, 140, 40, 0.5); }
/* a fine top highlight on every face: the plate catches light along its upper edge */
.te-face::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.5), transparent); pointer-events: none; }

/* ═════ each title's touch on its plate ═════ */
/* FIRST LIGHT (brass): one dawn sweep */
.te-first-light .te-face::after { content: ''; position: absolute; inset: 0; background: linear-gradient(100deg, transparent 38%, rgba(255, 250, 220, 0.9) 50%, transparent 62%); mix-blend-mode: screen; transform: translateX(-120%); animation: te-sweep 2.8s ease-out 0.5s 1 both; }
@keyframes te-sweep { to { transform: translateX(120%); } }
/* SECOND PAIR OF EYES (glass): one clean outline small; the double outline only large */
.te-second-pair-of-eyes .te-t { -webkit-text-stroke: 0.25px #9fd0e6; }
.te-sz-large.te-second-pair-of-eyes .te-t { color: transparent; -webkit-text-stroke: 0.7px #9fd0e6; text-shadow: none; }
.te-sz-large.te-second-pair-of-eyes .te-t::before, .te-sz-large.te-second-pair-of-eyes .te-t::after { content: attr(data-text); position: absolute; left: 0; top: 0; color: transparent; transition: transform 0.45s ease; }
.te-sz-large.te-second-pair-of-eyes .te-t::before { -webkit-text-stroke: 0.7px #ff8aa0; transform: translate(-2px, -1.3px); }
.te-sz-large.te-second-pair-of-eyes .te-t::after { -webkit-text-stroke: 0.7px #7fe3d6; transform: translate(2px, 1.3px); }
.te-sz-large.te-second-pair-of-eyes:hover .te-t::before, .te-sz-large.te-second-pair-of-eyes:hover .te-t::after { transform: translate(0, 0); }
/* BALLOT BEARER (wax): a small seal dot */
.te-ballot-bearer .te-face { padding-left: 1.9em; }
.te-ballot-bearer .te-face::after { content: ''; position: absolute; left: 0.7em; top: 50%; width: 0.62em; height: 0.62em; margin-top: -0.31em; border-radius: 50%; background: radial-gradient(circle at 35% 30%, #ffd9cf, #c33a2c 60%, #6e1410); box-shadow: 0 0 0 1px rgba(80, 10, 10, 0.6); }
/* EXACTLY ONCE (LED terminal): a typewriter, each letter typed once */
.te-exactly-once { letter-spacing: 0.14em; font-family: 'IBM Plex Mono', ui-monospace, monospace; }
.te-exactly-once .te-ch { opacity: 0; animation: te-type 0.01s linear forwards; animation-delay: calc(var(--i) * 0.07s + 0.3s); }
.te-exactly-once .te-t::after { content: ''; display: inline-block; width: 0.5em; height: 0.95em; margin-left: 2px; vertical-align: -0.1em; background: #7dffa0; animation: te-caret 1s steps(1) infinite; }
@keyframes te-type { to { opacity: 1; } }
@keyframes te-caret { 50% { opacity: 0; } }
/* MUTUALLY TRUSTED (steel): two interlocked hairlines under the word */
.te-mutually-trusted .te-face { padding-bottom: 0.95em; }
.te-mutually-trusted .te-face::after { content: ''; position: absolute; left: 12%; right: 12%; bottom: 0.3em; height: 0.46em; background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 8' preserveAspectRatio='none'><rect x='1' y='1.2' width='24' height='5.6' rx='2.8' fill='none' stroke='%231d4f8a' stroke-width='1'/><rect x='15' y='1.2' width='24' height='5.6' rx='2.8' fill='none' stroke='%237a4a06' stroke-width='1'/></svg>") center / 100% 100% no-repeat; }
/* KEEPER OF DELTA ZERO (LED panel): dot-matrix lettering and a live "Δ 0.0" */
.te-keeper-of-delta-zero .te-face { padding-right: 4.6em; }
.te-keeper-of-delta-zero .te-t { background: radial-gradient(circle at 1px 1px, #86ffa3 0.75px, rgba(134, 255, 163, 0.12) 1.2px) 0 0 / 2px 2px; -webkit-background-clip: text; background-clip: text; color: transparent; text-shadow: none; filter: drop-shadow(0 0 3px rgba(80, 255, 140, 0.5)); }
.te-sz-sidebar.te-keeper-of-delta-zero .te-t { background: none; color: #86ffa3; -webkit-background-clip: border-box; background-clip: border-box; }
.te-keeper-of-delta-zero .te-face::after { content: 'Δ 0.0'; position: absolute; right: 0.9em; top: 50%; transform: translateY(-50%); font-size: 0.9em; font-weight: 700; color: #86ffa3; padding: 0.15em 0.4em; border: 1px solid rgba(134, 255, 163, 0.5); letter-spacing: 0.04em; animation: te-led 2.4s steps(1) infinite; text-shadow: 0 0 4px rgba(80, 255, 140, 0.6); }
@keyframes te-led { 0%, 88%, 100% { opacity: 1; } 92% { opacity: 0.35; } }
/* SENATE SCRIBE (paper): a serif, light, and a quill stroke drawn under it once */
.te-senate-scribe { font-family: 'IBM Plex Serif', Georgia, 'Times New Roman', serif; font-weight: 300; font-style: italic; text-transform: none; letter-spacing: 0.06em; }
.te-senate-scribe .te-face { padding-bottom: 0.9em; }
.te-senate-scribe .te-face::after { content: ''; position: absolute; left: 1em; right: 1em; bottom: 0.32em; height: 0.34em; background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 6' preserveAspectRatio='none'><path d='M1 4.4 C18 1 34 5.4 52 3 S88 1.2 99 3.6' fill='none' stroke='%237a4a06' stroke-width='1.1' stroke-linecap='round'/></svg>") left / 100% 100% no-repeat; transform-origin: left; animation: te-draw 1.4s ease-out 0.4s 1 both; }
@keyframes te-draw { from { transform: scaleX(0); } to { transform: scaleX(1); } }
/* BUG SLAYER and IT WORKS ON MY FRAME (carbon): a glitch that settles / never quite does */
.te-bug-slayer .te-t::before, .te-bug-slayer .te-t::after, .te-it-works-on-my-frame .te-t::before, .te-it-works-on-my-frame .te-t::after { content: attr(data-text); position: absolute; left: 0; top: 0; opacity: 0; }
.te-bug-slayer .te-t::before { color: #ff3d6e; animation: te-gl-a 2.2s steps(1) 0.2s 1 both; }
.te-bug-slayer .te-t::after { color: #3dd9ff; animation: te-gl-b 2.2s steps(1) 0.2s 1 both; }
.te-bug-slayer:hover .te-t::before { animation: te-gl-a 1.2s steps(1) 1; }
.te-bug-slayer:hover .te-t::after { animation: te-gl-b 1.2s steps(1) 1; }
@keyframes te-gl-a { 0% { opacity: 1; transform: translate(calc(var(--g) * -1), 0); } 12% { opacity: 1; transform: translate(var(--g), -1px); } 26% { opacity: 1; transform: translate(-1px, 1px); } 40% { opacity: 0.8; transform: translate(1px, 0); } 60% { opacity: 0.5; transform: translate(0, 0); } 100% { opacity: 0; } }
@keyframes te-gl-b { 0% { opacity: 1; transform: translate(var(--g), 1px); } 15% { opacity: 1; transform: translate(calc(var(--g) * -1), 0); } 30% { opacity: 0.9; transform: translate(1px, -1px); } 52% { opacity: 0.5; transform: translate(0, 0); } 100% { opacity: 0; } }
.te-it-works-on-my-frame .te-t::before { color: #ff3d6e; animation: te-flk-a 5.5s steps(1) infinite; }
.te-it-works-on-my-frame .te-t::after { color: #3dd9ff; animation: te-flk-b 5.5s steps(1) infinite; }
@keyframes te-flk-a { 0%, 58%, 66%, 91%, 100% { opacity: 0; } 59% { opacity: 1; transform: translate(calc(var(--g) * -1), 1px); } 62% { opacity: 1; transform: translate(var(--g), -1px); } 92% { opacity: 1; transform: translate(-1px, 0); } 95% { opacity: 0.7; transform: translate(1px, 1px); } }
@keyframes te-flk-b { 0%, 57%, 67%, 90%, 100% { opacity: 0; } 60% { opacity: 1; transform: translate(var(--g), 0); } 64% { opacity: 1; transform: translate(calc(var(--g) * -1), 1px); } 93% { opacity: 1; transform: translate(1px, -1px); } }
/* ARCHITECT OF THE BEAST (blueprint film): a drawn border inside the plate */
.te-architect-of-the-beast .te-face::after { content: ''; position: absolute; inset: 2px; border: 1px solid rgba(190, 240, 255, 0.55); pointer-events: none; }
/* BEAST TAMER (iron): molten lettering, a gradient flowing slowly (two layers cross-fading) */
.te-beast-tamer .te-t { background: linear-gradient(90deg, #ff3d00, #ff9a1f 40%, #ffd166 60%, #ff3d00); -webkit-background-clip: text; background-clip: text; color: transparent; text-shadow: none; filter: drop-shadow(0 0 3px rgba(255, 90, 20, 0.5)); }
.te-beast-tamer .te-t::after { content: attr(data-text); position: absolute; left: 0; top: 0; background: linear-gradient(90deg, #ffd166, #ff3d00 35%, #ff9a1f 70%, #ffd166); -webkit-background-clip: text; background-clip: text; color: transparent; animation: te-fade 4.2s ease-in-out infinite; }
@keyframes te-fade { 0%, 100% { opacity: 0; } 50% { opacity: 1; } }
/* EVENT HORIZON (smoked glass): the letters lean into a thin amber accretion line */
.te-event-horizon .te-ch { transform: skewX(calc(var(--i) * -1.1deg)); opacity: calc(1 - var(--i) * 0.03); }
.te-event-horizon .te-face { padding-right: 2.2em; }
.te-event-horizon .te-face::after { content: ''; position: absolute; right: -0.2em; top: 50%; width: 2.4em; height: 0.7em; margin-top: -0.35em; border-radius: 50%; background: radial-gradient(ellipse, #000 38%, #ffb454 52%, rgba(255, 150, 60, 0.3) 62%, transparent 72%); animation: te-fade 5s ease-in-out infinite alternate; }
/* THE EYE SEES ALL (bronze): a quiet iris glow, ONE slit pupil in the E of Eye (none at the sidebar size) */
.te-the-eye-sees-all .te-face::after { content: ''; position: absolute; left: 50%; top: 50%; width: 120%; height: 160%; transform: translate(-50%, -50%); background: radial-gradient(ellipse, rgba(255, 170, 50, 0.32) 0%, rgba(200, 60, 20, 0.2) 40%, transparent 70%); animation: te-breathe 4.4s ease-in-out infinite; pointer-events: none; }
.te-the-eye-sees-all .te-o { position: relative; color: #ffe9b8; }
.te-the-eye-sees-all .te-o::after { content: ''; position: absolute; left: 50%; top: 20%; bottom: 14%; width: max(1.3px, 0.09em); margin-left: calc(max(1.3px, 0.09em) / -2); border-radius: 50%; background: #1a0305; box-shadow: 0 0 0 0.7px rgba(255, 207, 106, 0.85), 0 0 2px 0.5px rgba(255, 120, 30, 0.55); }
.te-sz-sidebar.te-the-eye-sees-all .te-o { color: inherit; }
.te-sz-sidebar.te-the-eye-sees-all .te-o::after { display: none; }
/* option B: the words plain; a clean almond eye as a mark at the plate's left (as the delta sits inset on Keeper of Delta Zero). His note (seq 4158): the
   eye must read as an eye at the sidebar size: a true almond (a 32 x 20 drawing, never squashed: the box keeps its ratio), a round iris, a slit pupil,
   about the cap height, outlined in the LIGHT ink so it stands off the bronze. */
.te-the-eye-sees-all.te-v-b .te-face { padding-left: 3.3em; }
.te-the-eye-sees-all.te-v-b .te-face::after {
  left: 0.8em; top: 50%; width: 1.92em; height: 1.2em; transform: translateY(-50%); animation: none; opacity: 1; border-radius: 0;
  background: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 20'><path d='M1.5 10 C7 2.6 12 1.4 16 1.4 S25 2.6 30.5 10 C25 17.4 20 18.6 16 18.6 S7 17.4 1.5 10 Z' fill='%23120a05' stroke='%23fff3d0' stroke-width='1.9' stroke-linejoin='round'/><circle cx='16' cy='10' r='6.6' fill='%23ffb830'/><circle cx='16' cy='10' r='6.6' fill='none' stroke='%23fff3d0' stroke-width='0.9'/><ellipse cx='16' cy='10' rx='1.5' ry='5.6' fill='%23120305'/><circle cx='13.6' cy='7.4' r='1.3' fill='%23ffffff'/></svg>") center / contain no-repeat;
}
.te-the-eye-sees-all.te-v-b .te-t { color: var(--ink); }
.te-the-eye-sees-all.te-v-b .te-o { color: inherit; }
.te-the-eye-sees-all.te-v-b .te-o::after { display: none; }
@keyframes te-breathe { 0%, 100% { opacity: 0.6; } 50% { opacity: 1; } }
/* FOUNDER OF THE COMMONS (foil): a second foil layer fading in and out over the first */
.te-founder-of-the-commons .te-face::after { content: ''; position: absolute; inset: 0; background: linear-gradient(110deg, #b6ffe2, #fff0a8 25%, #ffd1f5 50%, #a9c8ff 75%, #b6ffe2); mix-blend-mode: soft-light; animation: te-fade 3.6s ease-in-out infinite; }
/* OFF BY ONE (steel): one letter sits a pixel off */
.te-off-by-one .te-off { transform: translate(1px, 1px); color: #8a1a10; }
/* DEAD LETTER WHISPERER (paper): a postmark that fades */
.te-dead-letter-whisperer { font-style: italic; text-transform: none; letter-spacing: 0.08em; }
.te-dead-letter-whisperer .te-face { padding-right: 2.2em; }
.te-dead-letter-whisperer .te-face::after { content: ''; position: absolute; right: 0.7em; top: 50%; width: 1em; height: 1em; margin-top: -0.5em; border: 1px solid #a33c2e; border-radius: 50%; opacity: 0.7; transform: rotate(-14deg); animation: te-fade 6s ease-in-out infinite; }
/* ROLLBACK READY (brass): a rewind sweep running backwards */
.te-rollback-ready .te-face::after { content: ''; position: absolute; inset: 0; background: linear-gradient(80deg, transparent 38%, rgba(255, 255, 255, 0.8) 50%, transparent 62%); mix-blend-mode: screen; transform: translateX(120%); animation: te-sweep-back 3.6s ease-in-out 0.4s infinite; }
@keyframes te-sweep-back { 0%, 60%, 100% { transform: translateX(120%); } 85% { transform: translateX(-120%); } }
/* QUORUM MAKER (steel): five tally strokes that fill in */
.te-quorum-maker .te-face { padding-left: 3.5em; }
.te-quorum-maker .te-face::before { content: '||||'; position: absolute; left: 0.8em; top: 0.5em; width: auto; height: auto; background: none; letter-spacing: 0.1em; color: #0b2447; font-weight: 400; }
.te-quorum-maker .te-face::after { content: ''; position: absolute; left: 0.6em; top: 52%; width: 2.2em; height: 1.2px; background: #0b2447; transform-origin: left; transform: rotate(-24deg); animation: te-fade 5s ease-in-out infinite; }
/* CLEAN CHECKOUT (LED green): a check mark */
.te-clean-checkout .te-face { padding-left: 2em; }
.te-clean-checkout .te-face::after { content: '✓'; position: absolute; left: 0.75em; top: 50%; transform: translateY(-52%); color: #6dffa2; font-weight: 700; animation: te-fade 4s ease-in-out infinite alternate; }

/* ═════ the still frame (reduced motion, or the gallery's still view): a key moment of each effect ═════ */
@media (prefers-reduced-motion: reduce) {
  .te *, .te-face::before, .te-face::after, .te .te-t::before, .te .te-t::after { animation: none !important; transition: none !important; }
  .te-bug-slayer .te-t::before { opacity: 1; transform: translate(-1.2px, 0); clip-path: inset(18% 0 52% 0); }
  .te-bug-slayer .te-t::after { opacity: 1; transform: translate(1.2px, 0); clip-path: inset(56% 0 14% 0); }
  .te-it-works-on-my-frame .te-t::before { opacity: 1; transform: translate(-1.5px, 1px); clip-path: inset(34% 0 36% 0); }
  .te-it-works-on-my-frame .te-t::after { opacity: 1; transform: translate(1.5px, -1px); clip-path: inset(66% 0 4% 0); }
  .te-exactly-once .te-ch.te-typed { opacity: 1; }
  .te-exactly-once .te-t::after { opacity: 1; }
  .te-first-light .te-face::after { transform: translateX(-18%); opacity: 0.35; }
  .te-rollback-ready .te-face::after { transform: translateX(-30%); opacity: 0.3; }
  .te-beast-tamer .te-t::after { opacity: 0.45; }
  .te-founder-of-the-commons .te-face::after { opacity: 0.5; }
  .te-the-eye-sees-all .te-face::after { opacity: 0.85; }
  .te-senate-scribe .te-face::after { transform: none; }
}
.te-still *, .te-still .te-face::before, .te-still .te-face::after, .te-still .te-t::before, .te-still .te-t::after { animation: none !important; transition: none !important; }
.te-still.te-bug-slayer .te-t::before { opacity: 1; transform: translate(-1.2px, 0); clip-path: inset(18% 0 52% 0); }
.te-still.te-bug-slayer .te-t::after { opacity: 1; transform: translate(1.2px, 0); clip-path: inset(56% 0 14% 0); }
.te-still.te-it-works-on-my-frame .te-t::before { opacity: 1; transform: translate(-1.5px, 1px); clip-path: inset(34% 0 36% 0); }
.te-still.te-it-works-on-my-frame .te-t::after { opacity: 1; transform: translate(1.5px, -1px); clip-path: inset(66% 0 4% 0); }
.te-still.te-exactly-once .te-ch.te-typed { opacity: 1; }
.te-still.te-exactly-once .te-t::after { opacity: 1; }
.te-still.te-first-light .te-face::after { transform: translateX(-18%); opacity: 0.35; }
.te-still.te-rollback-ready .te-face::after { transform: translateX(-30%); opacity: 0.3; }
.te-still.te-beast-tamer .te-t::after { opacity: 0.45; }
.te-still.te-founder-of-the-commons .te-face::after { opacity: 0.5; }
.te-still.te-the-eye-sees-all .te-face::after { opacity: 0.85; }
.te-still.te-senate-scribe .te-face::after { transform: none; }
</style>
