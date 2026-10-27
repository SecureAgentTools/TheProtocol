<!--
  FlareEncirclement — encirclement-slot flare wrapper (PB-1 §11/§12/§14/§15).

  Wraps an avatar circle (image, initials, or icon) with an encirclement
  visual. Today only the `shadow_chancellor` tier renders encirclement;
  future encirclement-class tiers extend the visible set.

  ════════════════════════════════════════════════════════════════════════
  §15 (2026-05-13) — VARIANT v2 (AAA+ aesthetic pass)
  ════════════════════════════════════════════════════════════════════════
  Round 2 (2026-05-12) shipped the variant SYSTEM (4 palette-locked styles
  for Shadow Chancellor: sauron|goth|obsidian|void). Round 3 (today, §15)
  refines each variant from "structurally complete" to "Commander-grade":

    • sauron   — inline SVG iris with cat-pupil + flame aura + ember rise
                 + 7s blink. The eye actually reads as Sauron now (not a
                 red bump). Frame still breathes.
    • goth     — wetter blobs (blur 0.5→1.6px) with color variation per
                 compass-point (indigo north, magenta east, etc.) plus
                 meniscus highlights suggesting wet surface tension.
    • obsidian — 8 sharp prismatic facet bands (replaces soft conic),
                 static fresnel rim highlight (replaces sheen sweep),
                 60s rotation instead of 24s. Crisp polished stone.
    • void     — 7 concentric event-horizon rings + asymmetric photon ring
                 highlight at 11 o'clock (Interstellar reference) plus
                 slight ellipse-scale for gravitational lensing. Pure
                 jet-black core.

  Sizes:
    xs ─ 22px ─ sidebar/agent-card (sub-condensed; halos simplified)
    sm ─ 26px ─ list rows
    md ─ 36px ─ header avatar
    lg ─ 48px ─ profile-card
    xl ─ 96px ─ FoundersWall + FlareManager preview

  All variants honor `prefers-reduced-motion` (animations cancel).
  All variants observe the donut-mask pattern: halo rendering NEVER
  occludes the central avatar circle.
-->
<template>
  <span
    v-if="visible"
    class="fc-encircle"
    :class="[
      `fc-encircle-${tier}`,
      `fc-encircle-${effectiveVariant}`,
      `fc-encircle-size-${size}`,
      effectiveOverlay ? `fc-overlay-${effectiveOverlay}` : null,
    ]"
    role="img"
    :title="tooltip"
    :aria-label="tooltip"
  >
    <!-- §15 (2026-05-13): Sauron-only inline SVG eye. Sits above the
         encirclement frame, fixed to the top of the bbox so it reads as
         "watching from above". Vertical cat-pupil iris + flame aura +
         5 rising embers. Hidden at xs/sm sizes (detail would be lost). -->
    <span
      v-if="showSauronEye"
      class="fc-sauron-eye"
      aria-hidden="true"
    >
      <svg viewBox="0 0 140 90" preserveAspectRatio="xMidYMid meet">
        <defs>
          <!-- Outer fiery aura — saturated yellow→orange→crimson radial.
               Bright core punches through dark background. -->
          <radialGradient id="fc-sauron-flame" cx="50%" cy="50%" r="50%" fx="50%" fy="50%">
            <stop offset="0%"   stop-color="#fffbeb" stop-opacity="1"/>
            <stop offset="12%"  stop-color="#fde047" stop-opacity="0.96"/>
            <stop offset="28%"  stop-color="#fb923c" stop-opacity="0.88"/>
            <stop offset="50%"  stop-color="#dc2626" stop-opacity="0.70"/>
            <stop offset="76%"  stop-color="#7f1d1d" stop-opacity="0.35"/>
            <stop offset="100%" stop-color="#450a0a" stop-opacity="0"/>
          </radialGradient>
          <!-- Iris radial: bright pale-yellow rim → amber → crimson interior -->
          <radialGradient id="fc-sauron-iris" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stop-color="#fffbeb"/>
            <stop offset="20%"  stop-color="#fde047"/>
            <stop offset="55%"  stop-color="#f59e0b"/>
            <stop offset="84%"  stop-color="#b91c1c"/>
            <stop offset="100%" stop-color="#450a0a"/>
          </radialGradient>
          <!-- Inner eye-white halo (yellow glow inside the almond) -->
          <radialGradient id="fc-sauron-white" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stop-color="#fffbeb" stop-opacity="0.9"/>
            <stop offset="50%"  stop-color="#fde047" stop-opacity="0.7"/>
            <stop offset="100%" stop-color="#fb923c" stop-opacity="0.2"/>
          </radialGradient>
          <filter id="fc-sauron-flame-blur" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="1.4"/>
          </filter>
          <filter id="fc-sauron-iris-blur" x="-15%" y="-15%" width="130%" height="130%">
            <feGaussianBlur stdDeviation="0.3"/>
          </filter>
          <filter id="fc-sauron-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="2.2"/>
          </filter>
          <!-- Almond clip: crops the eye-white to canonical lens shape -->
          <clipPath id="fc-sauron-almond">
            <ellipse cx="70" cy="48" rx="42" ry="22"/>
          </clipPath>
        </defs>

        <!-- Outer GLOW (very wide, very soft — sells the burning aura) -->
        <ellipse cx="70" cy="48" rx="68" ry="36"
                 fill="url(#fc-sauron-flame)"
                 filter="url(#fc-sauron-glow)"
                 opacity="0.85"/>

        <!-- Mid flame layer — between outer glow and inner eye -->
        <ellipse cx="70" cy="48" rx="55" ry="28"
                 fill="url(#fc-sauron-flame)"
                 filter="url(#fc-sauron-flame-blur)"
                 class="fc-sauron-flame"/>

        <!-- Inner flame core (concentrated brightness in the iris zone) -->
        <ellipse cx="70" cy="48" rx="44" ry="22"
                 fill="url(#fc-sauron-flame)"
                 opacity="0.9"
                 class="fc-sauron-flame-core"/>

        <!-- Almond eye-WHITE (the lens shape) — yellow glow filling the
             eye socket, clipped to almond. -->
        <g clip-path="url(#fc-sauron-almond)">
          <ellipse cx="70" cy="48" rx="42" ry="22"
                   fill="url(#fc-sauron-white)"
                   opacity="0.95"/>
        </g>

        <!-- Almond rim — dark crimson outline tracing the eye shape -->
        <ellipse cx="70" cy="48" rx="42" ry="22"
                 fill="none"
                 stroke="rgba(127, 29, 29, 0.9)"
                 stroke-width="1.1"/>
        <!-- Inner secondary almond highlight rim — pale yellow -->
        <ellipse cx="70" cy="48" rx="38" ry="19"
                 fill="none"
                 stroke="rgba(254, 215, 170, 0.55)"
                 stroke-width="0.5"/>

        <!-- Eyelid group (blink animation) -->
        <g class="fc-sauron-eyelid">
          <!-- IRIS — bigger, more dominant. Vertical-elongated almond
               (rx=12 ry=18) gives the cat-pupil eye proportions. -->
          <ellipse cx="70" cy="48" rx="12" ry="18"
                   fill="url(#fc-sauron-iris)"
                   filter="url(#fc-sauron-iris-blur)"/>
          <!-- Inner iris bright zone -->
          <ellipse cx="70" cy="48" rx="8" ry="14"
                   fill="url(#fc-sauron-iris)"
                   opacity="0.9"/>
          <!-- PUPIL SLIT — vertical black cat-pupil, prominent + crisp -->
          <ellipse cx="70" cy="48" rx="2.8" ry="15.5" fill="#000"/>
          <!-- Inner crimson glow halo around pupil (depth) -->
          <ellipse cx="70" cy="48" rx="4" ry="16.5"
                   fill="none"
                   stroke="rgba(220, 38, 38, 0.7)"
                   stroke-width="0.6"
                   filter="url(#fc-sauron-iris-blur)"/>
          <!-- Catchlight highlights (life + depth) -->
          <ellipse cx="66" cy="39" rx="1.6" ry="2.8"
                   fill="rgba(255, 251, 235, 0.97)"/>
          <ellipse cx="73" cy="42" rx="0.8" ry="1.4"
                   fill="rgba(255, 251, 235, 0.75)"/>
        </g>

        <!-- Rising ember particles -->
        <g class="fc-sauron-embers">
          <circle cx="44" cy="72" r="1.0"  fill="#fb923c" class="fc-sauron-ember fc-sauron-ember-1"/>
          <circle cx="70" cy="76" r="1.3"  fill="#fde047" class="fc-sauron-ember fc-sauron-ember-2"/>
          <circle cx="96" cy="70" r="0.9"  fill="#dc2626" class="fc-sauron-ember fc-sauron-ember-3"/>
          <circle cx="54" cy="68" r="0.75" fill="#fb923c" class="fc-sauron-ember fc-sauron-ember-4"/>
          <circle cx="86" cy="74" r="0.85" fill="#fde047" class="fc-sauron-ember fc-sauron-ember-5"/>
        </g>
      </svg>
    </span>

    <span class="fc-encircle-frame">
      <!-- §18: BLACKHOLE variant REPLACES the avatar entirely. The frame
           interior is rendered as a pure black void with an inset photon
           ring at the rim. Hide avatar img + initials when blackhole.
           Show a tiny "drawing in" twinkle at the center to suggest
           gravity well presence. -->
      <span
        v-if="effectiveVariant === 'blackhole' && tier === 'shadow_chancellor'"
        class="fc-blackhole-core"
        aria-hidden="true"
      >
        <span class="fc-blackhole-singularity"></span>
      </span>

      <!-- ════════════════════════════════════════════════════════════════
           §pass67 (2026-05-23) — REGISTRY full-cover variants (18 NEW)
           All use tier="shadow_chancellor" (cosmetic, NOT SPIFFE-locked).
           Pattern mirrors blackhole: full-cover .fc-XXX-core span occludes
           the avatar (z-index: 1). Each is a unique inline-SVG mini-scene.
           ════════════════════════════════════════════════════════════════ -->

      <!-- A1 · CHANCELLERY — Bureaucratic mahogany seal with double-headed eagle -->
      <span v-if="effectiveVariant === 'chancellery' && tier === 'shadow_chancellor'" class="fc-chc-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-chc-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#6b2c1a"/>
              <stop offset="60%" stop-color="#3a1408"/>
              <stop offset="100%" stop-color="#1a0703"/>
            </radialGradient>
            <linearGradient id="fc-chc-brass" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#fde88a"/>
              <stop offset="55%" stop-color="#d4a13f"/>
              <stop offset="100%" stop-color="#7a4f12"/>
            </linearGradient>
            <filter id="fc-chc-glow"><feGaussianBlur stdDeviation="0.6"/></filter>
          </defs>
          <rect width="100" height="100" fill="url(#fc-chc-bg)"/>
          <!-- Brass outer annulus -->
          <circle cx="50" cy="50" r="46" fill="none" stroke="url(#fc-chc-brass)" stroke-width="2.2" opacity="0.88"/>
          <circle cx="50" cy="50" r="42" fill="none" stroke="rgba(254,232,138,0.32)" stroke-width="0.4" stroke-dasharray="1.5 3"/>
          <!-- 12 brass tick marks (60-sec clock) -->
          <g class="fc-chc-ticks" filter="url(#fc-chc-glow)">
            <circle cx="50" cy="8"  r="1.4" fill="#fde88a"/><circle cx="71" cy="14" r="1.4" fill="#fde88a"/>
            <circle cx="86" cy="29" r="1.4" fill="#fde88a"/><circle cx="92" cy="50" r="1.4" fill="#fde88a"/>
            <circle cx="86" cy="71" r="1.4" fill="#fde88a"/><circle cx="71" cy="86" r="1.4" fill="#fde88a"/>
            <circle cx="50" cy="92" r="1.4" fill="#fde88a"/><circle cx="29" cy="86" r="1.4" fill="#fde88a"/>
            <circle cx="14" cy="71" r="1.4" fill="#fde88a"/><circle cx="8"  cy="50" r="1.4" fill="#fde88a"/>
            <circle cx="14" cy="29" r="1.4" fill="#fde88a"/><circle cx="29" cy="14" r="1.4" fill="#fde88a"/>
          </g>
          <!-- Traveling brass pulse -->
          <circle class="fc-chc-pulse" cx="50" cy="8" r="1.9" fill="#fff4b8" filter="url(#fc-chc-glow)"/>
          <!-- Rotating brass minute-ring (60s authority gesture) -->
          <g class="fc-chc-rotor" transform-origin="50 50">
            <polygon points="50,18 56,30 50,28 44,30" fill="url(#fc-chc-brass)" opacity="0.78"/>
            <polygon points="82,50 70,56 72,50 70,44" fill="url(#fc-chc-brass)" opacity="0.55"/>
            <polygon points="50,82 44,70 50,72 56,70" fill="url(#fc-chc-brass)" opacity="0.55"/>
            <polygon points="18,50 30,44 28,50 30,56" fill="url(#fc-chc-brass)" opacity="0.55"/>
          </g>
          <!-- Wax-red ribbon spiral mid-rim -->
          <circle cx="50" cy="50" r="36" fill="none" stroke="#8b1414" stroke-width="1.4" opacity="0.45" stroke-dasharray="3 5"/>
          <!-- Double-headed eagle silhouette (centerpiece) -->
          <g class="fc-chc-eagle" transform-origin="50 50">
            <!-- body -->
            <path d="M50,38 L46,46 L43,55 L48,58 L52,58 L57,55 L54,46 Z" fill="url(#fc-chc-brass)" filter="url(#fc-chc-glow)"/>
            <!-- left head -->
            <path d="M46,40 L42,36 L40,32 L38,28 L42,30 L45,33 L47,38 Z" fill="url(#fc-chc-brass)"/>
            <!-- right head -->
            <path d="M54,40 L58,36 L60,32 L62,28 L58,30 L55,33 L53,38 Z" fill="url(#fc-chc-brass)"/>
            <!-- wings spread -->
            <path d="M43,48 L33,46 L26,52 L34,54 L42,52 Z" fill="url(#fc-chc-brass)" opacity="0.92"/>
            <path d="M57,48 L67,46 L74,52 L66,54 L58,52 Z" fill="url(#fc-chc-brass)" opacity="0.92"/>
            <!-- tail -->
            <path d="M48,60 L46,68 L50,70 L54,68 L52,60 Z" fill="url(#fc-chc-brass)"/>
            <!-- crown above heads -->
            <path d="M44,28 L46,24 L50,26 L54,24 L56,28 L52,28 L50,30 L48,28 Z" fill="#fde88a" stroke="#7a4f12" stroke-width="0.3"/>
          </g>
        </svg>
      </span>

      <!-- A2 · STATEHOUSE — Capitol dome silhouette over slate-blue sky -->
      <span v-if="effectiveVariant === 'statehouse' && tier === 'shadow_chancellor'" class="fc-sth-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-sth-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"  stop-color="#1e3a5f"/>
              <stop offset="55%" stop-color="#0f1c30"/>
              <stop offset="100%" stop-color="#050a14"/>
            </linearGradient>
            <linearGradient id="fc-sth-marble" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#fffaf0"/>
              <stop offset="100%" stop-color="#c0b8a8"/>
            </linearGradient>
            <radialGradient id="fc-sth-spot" cx="50%" cy="40%" r="35%">
              <stop offset="0%" stop-color="rgba(255,250,240,0.42)"/>
              <stop offset="100%" stop-color="rgba(255,250,240,0)"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-sth-sky)"/>
          <!-- soft spotlight on dome -->
          <rect width="100" height="100" fill="url(#fc-sth-spot)"/>
          <!-- dome (with slow lift animation via class) -->
          <g class="fc-sth-dome">
            <!-- dome cap -->
            <path d="M30,58 A20,18 0 0,1 70,58 L70,62 L30,62 Z" fill="url(#fc-sth-marble)" stroke="#7a7060" stroke-width="0.5"/>
            <!-- inset dome ribs -->
            <path d="M40,58 L40,46" stroke="#a39580" stroke-width="0.5" opacity="0.6"/>
            <path d="M50,58 L50,42" stroke="#a39580" stroke-width="0.5" opacity="0.6"/>
            <path d="M60,58 L60,46" stroke="#a39580" stroke-width="0.5" opacity="0.6"/>
            <!-- spire on top -->
            <line x1="50" y1="42" x2="50" y2="32" stroke="url(#fc-sth-marble)" stroke-width="1.4"/>
            <circle cx="50" cy="32" r="1.8" fill="#fde88a"/>
            <!-- colonnade base -->
            <rect x="22" y="62" width="56" height="4" fill="url(#fc-sth-marble)"/>
            <!-- 8 columns -->
            <g fill="url(#fc-sth-marble)">
              <rect x="24" y="66" width="2.5" height="14"/>
              <rect x="30" y="66" width="2.5" height="14"/>
              <rect x="36" y="66" width="2.5" height="14"/>
              <rect x="42" y="66" width="2.5" height="14"/>
              <rect x="49" y="66" width="2.5" height="14"/>
              <rect x="55" y="66" width="2.5" height="14"/>
              <rect x="61" y="66" width="2.5" height="14"/>
              <rect x="67" y="66" width="2.5" height="14"/>
              <rect x="73" y="66" width="2.5" height="14"/>
            </g>
            <!-- steps -->
            <rect x="20" y="80" width="60" height="2" fill="#9c9080"/>
            <rect x="18" y="82" width="64" height="2" fill="#7a7060"/>
          </g>
          <!-- stars in sky -->
          <g class="fc-sth-stars" fill="#fff4d8">
            <circle cx="18" cy="20" r="0.5"/><circle cx="84" cy="14" r="0.6"/>
            <circle cx="72" cy="24" r="0.4"/><circle cx="26" cy="36" r="0.5"/>
            <circle cx="92" cy="38" r="0.4"/>
          </g>
        </svg>
      </span>

      <!-- A3 · BASTILLE — Fortified rampart with crenellation + torches -->
      <span v-if="effectiveVariant === 'bastille' && tier === 'shadow_chancellor'" class="fc-bst-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-bst-stone" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#5c5046"/>
              <stop offset="60%" stop-color="#382f28"/>
              <stop offset="100%" stop-color="#1a1410"/>
            </linearGradient>
            <linearGradient id="fc-bst-banner" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#a02828"/>
              <stop offset="100%" stop-color="#4a0a0a"/>
            </linearGradient>
            <radialGradient id="fc-bst-torch" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#fff4b8"/>
              <stop offset="35%" stop-color="#ff8c1c"/>
              <stop offset="100%" stop-color="rgba(160,40,0,0)"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-bst-stone)"/>
          <!-- mortar texture -->
          <g stroke="#1a1410" stroke-width="0.4" opacity="0.55">
            <line x1="0" y1="42" x2="100" y2="42"/>
            <line x1="0" y1="60" x2="100" y2="60"/>
            <line x1="14" y1="42" x2="14" y2="60"/>
            <line x1="32" y1="42" x2="32" y2="60"/>
            <line x1="52" y1="42" x2="52" y2="60"/>
            <line x1="68" y1="42" x2="68" y2="60"/>
            <line x1="86" y1="42" x2="86" y2="60"/>
            <line x1="22" y1="60" x2="22" y2="78"/>
            <line x1="44" y1="60" x2="44" y2="78"/>
            <line x1="60" y1="60" x2="60" y2="78"/>
            <line x1="78" y1="60" x2="78" y2="78"/>
          </g>
          <!-- crenellation notches at top -->
          <g fill="url(#fc-bst-stone)" stroke="#1a1410" stroke-width="0.5">
            <rect x="14" y="24" width="10" height="10"/>
            <rect x="30" y="24" width="10" height="10"/>
            <rect x="46" y="24" width="10" height="10"/>
            <rect x="62" y="24" width="10" height="10"/>
            <rect x="78" y="24" width="8"  height="10"/>
          </g>
          <!-- portcullis bars -->
          <g stroke="#3a2814" stroke-width="1.4" opacity="0.92">
            <line x1="42" y1="46" x2="42" y2="76"/>
            <line x1="50" y1="46" x2="50" y2="76"/>
            <line x1="58" y1="46" x2="58" y2="76"/>
            <line x1="38" y1="58" x2="62" y2="58"/>
            <line x1="38" y1="70" x2="62" y2="70"/>
          </g>
          <!-- heraldic banner mid-wall -->
          <g class="fc-bst-banner">
            <path d="M45,52 L55,52 L55,72 L50,68 L45,72 Z" fill="url(#fc-bst-banner)"/>
            <!-- gold cross -->
            <path d="M48,56 L52,56 L52,60 L48,60 Z M49.5,54 L50.5,54 L50.5,62 L49.5,62 Z" fill="#fde88a"/>
          </g>
          <!-- 4 torch sconces -->
          <circle class="fc-bst-torch-1" cx="18" cy="50" r="3.5" fill="url(#fc-bst-torch)"/>
          <circle class="fc-bst-torch-2" cx="82" cy="50" r="3.5" fill="url(#fc-bst-torch)"/>
          <circle class="fc-bst-torch-3" cx="22" cy="78" r="3" fill="url(#fc-bst-torch)"/>
          <circle class="fc-bst-torch-4" cx="78" cy="78" r="3" fill="url(#fc-bst-torch)"/>
        </svg>
      </span>

      <!-- A4 · MINISTRY — Typewriter platen + serif glyph ribbon -->
      <span v-if="effectiveVariant === 'ministry' && tier === 'shadow_chancellor'" class="fc-min-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-min-bg" cx="50%" cy="50%" r="60%">
              <stop offset="0%" stop-color="#3a4a3a"/>
              <stop offset="100%" stop-color="#0e1812"/>
            </radialGradient>
            <linearGradient id="fc-min-paper" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#f0e8c8"/>
              <stop offset="100%" stop-color="#c8b888"/>
            </linearGradient>
            <linearGradient id="fc-min-platen" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#3a2a1a"/>
              <stop offset="100%" stop-color="#0a0604"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-min-bg)"/>
          <!-- typewriter ribbon spiral around rim -->
          <g class="fc-min-ribbon" transform-origin="50 50">
            <circle cx="50" cy="50" r="44" fill="none" stroke="#1a0e08" stroke-width="3.2" opacity="0.65"/>
            <!-- serif glyphs on ribbon -->
            <text x="50" y="11" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Α</text>
            <text x="80" y="22" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Β</text>
            <text x="92" y="54" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Γ</text>
            <text x="80" y="84" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Δ</text>
            <text x="50" y="94" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Ε</text>
            <text x="20" y="84" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Ζ</text>
            <text x="8"  y="54" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Η</text>
            <text x="20" y="22" fill="#f0e8c8" font-family="'Times New Roman',serif" font-size="6" font-weight="700" text-anchor="middle">Θ</text>
          </g>
          <!-- platen cylinder -->
          <rect x="22" y="42" width="56" height="22" rx="11" fill="url(#fc-min-platen)" stroke="#1a0e08" stroke-width="0.6"/>
          <!-- paper sheet rolled over platen -->
          <rect x="26" y="46" width="48" height="18" rx="1" fill="url(#fc-min-paper)" stroke="#7a6028" stroke-width="0.4"/>
          <!-- typewritten lines -->
          <g class="fc-min-text" fill="#3a2a1a" font-family="'Courier New',monospace" font-size="3.5">
            <text x="29" y="52">REGISTRAR</text>
            <text x="29" y="57">FILED · SEAL</text>
            <text x="29" y="62">ARCHIVED ✓</text>
          </g>
          <!-- inkwell at bottom -->
          <ellipse cx="50" cy="80" rx="6" ry="2.5" fill="#0a0604" stroke="#3a2a1a" stroke-width="0.5"/>
          <ellipse class="fc-min-ink" cx="50" cy="79" rx="3" ry="1.2" fill="#1a0e3a" opacity="0.85"/>
        </svg>
      </span>

      <!-- B1 · OLIVE-BRANCH — Peace wreath crossed branches -->
      <span v-if="effectiveVariant === 'olive-branch' && tier === 'shadow_chancellor'" class="fc-olv-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-olv-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#f4f0d8"/>
              <stop offset="65%" stop-color="#cbd2b8"/>
              <stop offset="100%" stop-color="#5a6448"/>
            </radialGradient>
            <linearGradient id="fc-olv-leaf" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#7ea158"/>
              <stop offset="100%" stop-color="#3e5828"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-olv-bg)"/>
          <!-- left branch arching up -->
          <path class="fc-olv-branch-l" d="M30,78 Q30,55 40,40 Q48,25 50,18" stroke="#5a4828" stroke-width="1.2" fill="none"/>
          <!-- right branch arching up -->
          <path class="fc-olv-branch-r" d="M70,78 Q70,55 60,40 Q52,25 50,18" stroke="#5a4828" stroke-width="1.2" fill="none"/>
          <!-- left-side leaves (drawn along the curve) -->
          <g class="fc-olv-leaves-l" fill="url(#fc-olv-leaf)">
            <ellipse cx="34" cy="68" rx="3" ry="1.5" transform="rotate(-30 34 68)"/>
            <ellipse cx="30" cy="58" rx="3.4" ry="1.7" transform="rotate(-20 30 58)"/>
            <ellipse cx="33" cy="48" rx="3" ry="1.5" transform="rotate(-50 33 48)"/>
            <ellipse cx="38" cy="40" rx="3.6" ry="1.8" transform="rotate(-65 38 40)"/>
            <ellipse cx="43" cy="32" rx="3" ry="1.5" transform="rotate(-78 43 32)"/>
            <ellipse cx="46" cy="24" rx="3.4" ry="1.7" transform="rotate(-88 46 24)"/>
          </g>
          <!-- right-side leaves -->
          <g class="fc-olv-leaves-r" fill="url(#fc-olv-leaf)">
            <ellipse cx="66" cy="68" rx="3" ry="1.5" transform="rotate(30 66 68)"/>
            <ellipse cx="70" cy="58" rx="3.4" ry="1.7" transform="rotate(20 70 58)"/>
            <ellipse cx="67" cy="48" rx="3" ry="1.5" transform="rotate(50 67 48)"/>
            <ellipse cx="62" cy="40" rx="3.6" ry="1.8" transform="rotate(65 62 40)"/>
            <ellipse cx="57" cy="32" rx="3" ry="1.5" transform="rotate(78 57 32)"/>
            <ellipse cx="54" cy="24" rx="3.4" ry="1.7" transform="rotate(88 54 24)"/>
          </g>
          <!-- olive fruits -->
          <g fill="#3a4818">
            <circle cx="36" cy="55" r="1.2"/>
            <circle cx="64" cy="55" r="1.2"/>
            <circle cx="40" cy="34" r="1.1"/>
            <circle cx="60" cy="34" r="1.1"/>
          </g>
          <!-- ribbon tie at base -->
          <path d="M44,76 L56,76 L52,82 L48,82 Z" fill="#f0d878" stroke="#7a5028" stroke-width="0.4"/>
          <!-- dove silhouette at center -->
          <g class="fc-olv-dove" fill="#fff8e8">
            <ellipse cx="50" cy="56" rx="6" ry="3.5"/>
            <ellipse cx="55" cy="53" rx="2.5" ry="1.8"/>
            <path d="M58,54 L62,52 L60,55 Z" fill="#fff8e8"/>
            <path d="M44,56 Q48,58 44,60" stroke="#fff8e8" stroke-width="1.5" fill="none"/>
          </g>
        </svg>
      </span>

      <!-- B2 · CROSS-SHIELD — Humanitarian red cross on white shield -->
      <span v-if="effectiveVariant === 'cross-shield' && tier === 'shadow_chancellor'" class="fc-csh-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-csh-bg" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#e8eef4"/>
              <stop offset="100%" stop-color="#8a9bab"/>
            </linearGradient>
            <linearGradient id="fc-csh-shield" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#ffffff"/>
              <stop offset="100%" stop-color="#c8d0d8"/>
            </linearGradient>
            <linearGradient id="fc-csh-red" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#e72a2a"/>
              <stop offset="100%" stop-color="#9c0a0a"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-csh-bg)"/>
          <!-- shield outline -->
          <path d="M50,18 L78,28 L78,55 Q78,75 50,85 Q22,75 22,55 L22,28 Z" fill="url(#fc-csh-shield)" stroke="#3a4856" stroke-width="1.2"/>
          <!-- cyan trim band -->
          <path d="M50,21 L75,30 L75,55 Q75,73 50,82 Q25,73 25,55 L25,30 Z" fill="none" stroke="#0fc8d0" stroke-width="0.8" opacity="0.85"/>
          <!-- red cross (humanitarian) -->
          <g class="fc-csh-cross" fill="url(#fc-csh-red)">
            <rect x="44" y="32" width="12" height="36" rx="0.5"/>
            <rect x="32" y="44" width="36" height="12" rx="0.5"/>
          </g>
          <!-- highlight glints on cross -->
          <rect x="45" y="33" width="3" height="34" fill="rgba(255,255,255,0.32)"/>
          <rect x="33" y="45" width="34" height="3" fill="rgba(255,255,255,0.32)"/>
          <!-- subtle banner-text strip at base -->
          <rect x="34" y="78" width="32" height="4" fill="#0fc8d0" opacity="0.45"/>
        </svg>
      </span>

      <!-- B3 · LIGHTHOUSE — Beacon tower with rotating cyan beam -->
      <span v-if="effectiveVariant === 'lighthouse' && tier === 'shadow_chancellor'" class="fc-lhs-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-lhs-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#0a1c2a"/>
              <stop offset="60%" stop-color="#03101a"/>
              <stop offset="100%" stop-color="#000508"/>
            </linearGradient>
            <linearGradient id="fc-lhs-tower" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#f0e8d8"/>
              <stop offset="50%" stop-color="#c0b8a8"/>
              <stop offset="100%" stop-color="#807868"/>
            </linearGradient>
            <radialGradient id="fc-lhs-beam" cx="0%" cy="50%" r="80%">
              <stop offset="0%" stop-color="rgba(180,240,255,0.95)"/>
              <stop offset="40%" stop-color="rgba(80,200,240,0.45)"/>
              <stop offset="100%" stop-color="rgba(20,150,200,0)"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-lhs-sky)"/>
          <!-- ocean wave line -->
          <path d="M0,82 Q25,78 50,82 T100,82 L100,100 L0,100 Z" fill="#0a4060" opacity="0.55"/>
          <path d="M0,86 Q25,84 50,86 T100,86" stroke="#0fc8d0" stroke-width="0.4" fill="none" opacity="0.65"/>
          <!-- lighthouse tower -->
          <g>
            <!-- base -->
            <rect x="42" y="70" width="16" height="12" fill="url(#fc-lhs-tower)"/>
            <!-- main tower with red stripes -->
            <rect x="44" y="40" width="12" height="30" fill="url(#fc-lhs-tower)"/>
            <rect x="44" y="45" width="12" height="3" fill="#c8302a"/>
            <rect x="44" y="55" width="12" height="3" fill="#c8302a"/>
            <rect x="44" y="65" width="12" height="3" fill="#c8302a"/>
            <!-- lamp room -->
            <rect x="42" y="30" width="16" height="10" fill="#3a2828" stroke="#1a0e08" stroke-width="0.5"/>
            <rect x="44" y="32" width="12" height="6" fill="#fff4b8"/>
            <!-- spire on top -->
            <path d="M46,30 L50,22 L54,30 Z" fill="#c8302a"/>
            <circle cx="50" cy="22" r="1.2" fill="#fde88a"/>
            <!-- door -->
            <rect x="47" y="74" width="6" height="8" fill="#3a2a14"/>
          </g>
          <!-- rotating beam -->
          <g class="fc-lhs-beam-rotor" transform-origin="50 35">
            <path d="M50,35 L98,18 L98,52 Z" fill="url(#fc-lhs-beam)" opacity="0.75"/>
            <path d="M50,35 L2,18 L2,52 Z" fill="url(#fc-lhs-beam)" opacity="0.45"/>
          </g>
          <!-- 12 navigation beacons on rim -->
          <g class="fc-lhs-beacons" fill="#0fc8d0" opacity="0.5">
            <circle cx="50" cy="6" r="0.9"/><circle cx="72" cy="13" r="0.9"/>
            <circle cx="86" cy="28" r="0.9"/><circle cx="93" cy="50" r="0.9"/>
            <circle cx="86" cy="72" r="0.9"/><circle cx="72" cy="87" r="0.9"/>
            <circle cx="50" cy="94" r="0.9"/><circle cx="28" cy="87" r="0.9"/>
            <circle cx="14" cy="72" r="0.9"/><circle cx="7"  cy="50" r="0.9"/>
            <circle cx="14" cy="28" r="0.9"/><circle cx="28" cy="13" r="0.9"/>
          </g>
        </svg>
      </span>

      <!-- B4 · COMMONS — Interlocking rings over creative-commons grid -->
      <span v-if="effectiveVariant === 'commons' && tier === 'shadow_chancellor'" class="fc-cmn-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-cmn-bg" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#1a3030"/>
              <stop offset="100%" stop-color="#0a1818"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-cmn-bg)"/>
          <!-- grid backdrop -->
          <g stroke="rgba(120,200,180,0.18)" stroke-width="0.3">
            <line x1="0" y1="20" x2="100" y2="20"/><line x1="0" y1="40" x2="100" y2="40"/>
            <line x1="0" y1="60" x2="100" y2="60"/><line x1="0" y1="80" x2="100" y2="80"/>
            <line x1="20" y1="0" x2="20" y2="100"/><line x1="40" y1="0" x2="40" y2="100"/>
            <line x1="60" y1="0" x2="60" y2="100"/><line x1="80" y1="0" x2="80" y2="100"/>
          </g>
          <!-- 5 interlocking rings -->
          <g class="fc-cmn-rings" fill="none" stroke-width="2.4">
            <!-- top row -->
            <circle cx="34" cy="42" r="13" stroke="#3a8fcc"/>
            <circle cx="50" cy="42" r="13" stroke="#0a0a0a" opacity="0.92"/>
            <circle cx="66" cy="42" r="13" stroke="#c83a3a"/>
            <!-- bottom row -->
            <circle cx="42" cy="58" r="13" stroke="#f0c828"/>
            <circle cx="58" cy="58" r="13" stroke="#3aaa48"/>
          </g>
          <!-- inward arrows pointing toward center -->
          <g class="fc-cmn-arrows" fill="rgba(180,240,200,0.62)">
            <path d="M10,50 L22,46 L22,54 Z"/>
            <path d="M90,50 L78,46 L78,54 Z"/>
            <path d="M50,10 L46,22 L54,22 Z"/>
            <path d="M50,90 L46,78 L54,78 Z"/>
          </g>
        </svg>
      </span>

      <!-- C1 · MOONSHOT — Cartoon rocket with chromatic trails -->
      <span v-if="effectiveVariant === 'moonshot' && tier === 'shadow_chancellor'" class="fc-mns-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-mns-bg" x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="#1a0238"/>
              <stop offset="50%" stop-color="#5e0a5e"/>
              <stop offset="100%" stop-color="#0a1a4a"/>
            </linearGradient>
            <linearGradient id="fc-mns-trail" x1="0%" y1="100%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="rgba(255,40,180,0.05)"/>
              <stop offset="50%" stop-color="rgba(255,180,40,0.65)"/>
              <stop offset="100%" stop-color="rgba(255,255,180,0.95)"/>
            </linearGradient>
            <linearGradient id="fc-mns-body" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#f0f8ff"/>
              <stop offset="100%" stop-color="#8090a8"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-mns-bg)"/>
          <!-- starfield -->
          <g fill="#fff4d8" class="fc-mns-stars">
            <circle cx="14" cy="22" r="0.6"/><circle cx="82" cy="14" r="0.4"/>
            <circle cx="24" cy="78" r="0.5"/><circle cx="74" cy="84" r="0.6"/>
            <circle cx="92" cy="48" r="0.4"/><circle cx="8" cy="60" r="0.4"/>
            <circle cx="64" cy="14" r="0.3"/><circle cx="36" cy="92" r="0.4"/>
          </g>
          <!-- rocket trail (chromatic) -->
          <g class="fc-mns-trails">
            <path d="M28,78 Q38,62 50,50" stroke="url(#fc-mns-trail)" stroke-width="6" fill="none" stroke-linecap="round" opacity="0.85"/>
            <path d="M22,84 Q34,68 46,54" stroke="#ff40b8" stroke-width="2.4" fill="none" stroke-linecap="round" opacity="0.7"/>
            <path d="M34,82 Q44,66 54,52" stroke="#fde04a" stroke-width="2" fill="none" stroke-linecap="round" opacity="0.8"/>
          </g>
          <!-- rocket body (pointing up-right) -->
          <g class="fc-mns-rocket" transform="translate(50 50) rotate(-45)">
            <!-- main body -->
            <path d="M-4,-18 L4,-18 L7,8 L-7,8 Z" fill="url(#fc-mns-body)" stroke="#3a4858" stroke-width="0.5"/>
            <!-- nose cone -->
            <path d="M-4,-18 L0,-26 L4,-18 Z" fill="#c8302a"/>
            <!-- window -->
            <circle cx="0" cy="-10" r="3" fill="#3a90cc" stroke="#1a4878" stroke-width="0.6"/>
            <circle cx="-1" cy="-11" r="0.8" fill="rgba(255,255,255,0.6)"/>
            <!-- fins -->
            <path d="M-7,8 L-12,14 L-4,8 Z" fill="#c8302a"/>
            <path d="M7,8 L12,14 L4,8 Z" fill="#c8302a"/>
            <!-- exhaust flame -->
            <path d="M-4,8 L-2,18 L0,12 L2,18 L4,8 Z" fill="#fde04a"/>
          </g>
          <!-- text-band on the outer ring -->
          <g class="fc-mns-text">
            <path id="fc-mns-textpath" d="M50,8 A42,42 0 0,1 92,50" fill="none"/>
            <text font-family="Impact,Arial Black,sans-serif" font-size="6.5" fill="#fde04a" font-weight="900" letter-spacing="1">
              <textPath href="#fc-mns-textpath" startOffset="10%">ALL SYSTEMS GO ★</textPath>
            </text>
          </g>
        </svg>
      </span>

      <!-- C2 · DIAMOND-HANDS — Faceted diamond shards radiating -->
      <span v-if="effectiveVariant === 'diamond-hands' && tier === 'shadow_chancellor'" class="fc-dmh-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-dmh-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#dceaf4"/>
              <stop offset="55%" stop-color="#8eaec8"/>
              <stop offset="100%" stop-color="#1a3858"/>
            </radialGradient>
            <linearGradient id="fc-dmh-facet-a" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="rgba(255,255,255,0.92)"/>
              <stop offset="100%" stop-color="rgba(180,228,255,0.45)"/>
            </linearGradient>
            <linearGradient id="fc-dmh-facet-b" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stop-color="rgba(120,200,255,0.85)"/>
              <stop offset="100%" stop-color="rgba(20,80,160,0.32)"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-dmh-bg)"/>
          <!-- 6 diamond shards radiating from center -->
          <g class="fc-dmh-shards" transform-origin="50 50">
            <!-- top -->
            <polygon points="50,50 46,28 50,8 54,28" fill="url(#fc-dmh-facet-a)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-1"/>
            <!-- top-right -->
            <polygon points="50,50 66,38 88,28 70,46" fill="url(#fc-dmh-facet-b)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-2"/>
            <!-- bottom-right -->
            <polygon points="50,50 66,62 88,72 70,54" fill="url(#fc-dmh-facet-a)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-3"/>
            <!-- bottom -->
            <polygon points="50,50 46,72 50,92 54,72" fill="url(#fc-dmh-facet-b)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-4"/>
            <!-- bottom-left -->
            <polygon points="50,50 34,62 12,72 30,54" fill="url(#fc-dmh-facet-a)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-5"/>
            <!-- top-left -->
            <polygon points="50,50 34,38 12,28 30,46" fill="url(#fc-dmh-facet-b)" stroke="rgba(255,255,255,0.85)" stroke-width="0.4" class="fc-dmh-shard-6"/>
          </g>
          <!-- center: fists clenched (stylized) -->
          <g class="fc-dmh-fists" fill="#1a2838" stroke="rgba(255,255,255,0.4)" stroke-width="0.3">
            <!-- left fist -->
            <ellipse cx="44" cy="50" rx="5" ry="4"/>
            <line x1="40" y1="48" x2="48" y2="48" stroke="#3a4858" stroke-width="0.6"/>
            <line x1="40" y1="51" x2="48" y2="51" stroke="#3a4858" stroke-width="0.6"/>
            <!-- right fist -->
            <ellipse cx="56" cy="50" rx="5" ry="4"/>
            <line x1="52" y1="48" x2="60" y2="48" stroke="#3a4858" stroke-width="0.6"/>
            <line x1="52" y1="51" x2="60" y2="51" stroke="#3a4858" stroke-width="0.6"/>
            <!-- knuckle highlights -->
            <circle cx="42" cy="48" r="0.8" fill="#7eb8e8"/>
            <circle cx="58" cy="48" r="0.8" fill="#7eb8e8"/>
          </g>
        </svg>
      </span>

      <!-- C3 · CHAD-FROG — Stylized cartoon frog face -->
      <span v-if="effectiveVariant === 'chad-frog' && tier === 'shadow_chancellor'" class="fc-cfg-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-cfg-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#3a6428"/>
              <stop offset="100%" stop-color="#0a1808"/>
            </radialGradient>
            <radialGradient id="fc-cfg-face" cx="50%" cy="55%" r="55%">
              <stop offset="0%" stop-color="#9cc848"/>
              <stop offset="100%" stop-color="#3a5418"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-cfg-bg)"/>
          <!-- frog face circle -->
          <circle cx="50" cy="56" r="32" fill="url(#fc-cfg-face)" stroke="#1a3008" stroke-width="0.8"/>
          <!-- left eye bump -->
          <circle cx="36" cy="36" r="10" fill="url(#fc-cfg-face)" stroke="#1a3008" stroke-width="0.8"/>
          <!-- right eye bump -->
          <circle cx="64" cy="36" r="10" fill="url(#fc-cfg-face)" stroke="#1a3008" stroke-width="0.8"/>
          <!-- left eyeball -->
          <circle cx="36" cy="36" r="6" fill="#ffffff"/>
          <ellipse class="fc-cfg-eye-l" cx="37" cy="36" rx="3" ry="4" fill="#0a0a0a"/>
          <circle cx="38" cy="34" r="1.2" fill="#ffffff"/>
          <!-- right eyeball with monocle -->
          <circle cx="64" cy="36" r="6" fill="#ffffff"/>
          <ellipse class="fc-cfg-eye-r" cx="63" cy="36" rx="3" ry="4" fill="#0a0a0a"/>
          <circle cx="62" cy="34" r="1.2" fill="#ffffff"/>
          <!-- monocle ring -->
          <circle cx="64" cy="36" r="8.5" fill="none" stroke="#fde04a" stroke-width="1.4" class="fc-cfg-monocle"/>
          <line x1="71" y1="40" x2="76" y2="48" stroke="#fde04a" stroke-width="0.8"/>
          <!-- smug smile -->
          <path d="M36,60 Q50,72 64,60" stroke="#1a3008" stroke-width="1.8" fill="none" stroke-linecap="round"/>
          <!-- inner mouth highlight -->
          <path d="M40,63 Q50,69 60,63" stroke="#5a8038" stroke-width="0.6" fill="none" opacity="0.6"/>
          <!-- "ok" hand at 5 o'clock -->
          <g class="fc-cfg-hand" transform="translate(78 68)">
            <circle cx="0" cy="0" r="2.5" fill="#9cc848" stroke="#1a3008" stroke-width="0.4"/>
            <path d="M-1.6,-0.8 L1.6,-0.8 L1.2,1.6 L-1.2,1.6 Z" fill="#1a3008" opacity="0.55"/>
          </g>
        </svg>
      </span>

      <!-- C4 · PIXEL-SHRINE — 8-bit altar with floating AVT coin -->
      <span v-if="effectiveVariant === 'pixel-shrine' && tier === 'shadow_chancellor'" class="fc-pxs-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" shape-rendering="crispEdges">
          <defs>
            <linearGradient id="fc-pxs-bg" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#3a1a5a"/>
              <stop offset="100%" stop-color="#10042a"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-pxs-bg)"/>
          <!-- chequered tile floor (16x16 grid) -->
          <g class="fc-pxs-floor">
            <rect x="20" y="72" width="10" height="10" fill="#5a3a8a"/><rect x="30" y="72" width="10" height="10" fill="#3a1a5a"/>
            <rect x="40" y="72" width="10" height="10" fill="#5a3a8a"/><rect x="50" y="72" width="10" height="10" fill="#3a1a5a"/>
            <rect x="60" y="72" width="10" height="10" fill="#5a3a8a"/><rect x="70" y="72" width="10" height="10" fill="#3a1a5a"/>
            <rect x="20" y="82" width="10" height="10" fill="#3a1a5a"/><rect x="30" y="82" width="10" height="10" fill="#5a3a8a"/>
            <rect x="40" y="82" width="10" height="10" fill="#3a1a5a"/><rect x="50" y="82" width="10" height="10" fill="#5a3a8a"/>
            <rect x="60" y="82" width="10" height="10" fill="#3a1a5a"/><rect x="70" y="82" width="10" height="10" fill="#5a3a8a"/>
          </g>
          <!-- altar pedestal -->
          <g class="fc-pxs-altar">
            <rect x="34" y="56" width="32" height="6" fill="#a08068"/>
            <rect x="36" y="62" width="28" height="10" fill="#7a5848"/>
            <rect x="34" y="72" width="32" height="3" fill="#a08068"/>
            <!-- candles -->
            <rect x="38" y="48" width="3" height="8" fill="#f0e0c8"/>
            <rect x="59" y="48" width="3" height="8" fill="#f0e0c8"/>
            <!-- candle flames -->
            <rect class="fc-pxs-flame-1" x="38" y="44" width="3" height="4" fill="#fde04a"/>
            <rect class="fc-pxs-flame-2" x="59" y="44" width="3" height="4" fill="#fde04a"/>
            <rect class="fc-pxs-flame-1" x="38" y="42" width="3" height="2" fill="#ff8c1c"/>
            <rect class="fc-pxs-flame-2" x="59" y="42" width="3" height="2" fill="#ff8c1c"/>
          </g>
          <!-- floating star token (rotating 4-frame) -->
          <g class="fc-pxs-coin" transform-origin="50 36">
            <rect x="42" y="26" width="16" height="16" fill="#fde04a" stroke="#7a5028" stroke-width="0.5"/>
            <rect x="44" y="28" width="12" height="12" fill="#fff4b8"/>
            <!-- star glyph -->
            <text x="50" y="38" font-family="monospace" font-size="9" font-weight="900" fill="#7a5028" text-anchor="middle">★</text>
          </g>
          <!-- floor sparkles -->
          <g class="fc-pxs-sparkles" fill="#ffffff">
            <rect x="22" y="76" width="1" height="1"/><rect x="76" y="84" width="1" height="1"/>
            <rect x="48" y="80" width="1" height="1"/>
          </g>
        </svg>
      </span>

      <!-- D1 · SAVANNA — African horizon with acacia silhouettes -->
      <span v-if="effectiveVariant === 'savanna' && tier === 'shadow_chancellor'" class="fc-svn-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-svn-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#3a1808"/>
              <stop offset="40%" stop-color="#c84818"/>
              <stop offset="70%" stop-color="#f0a048"/>
              <stop offset="100%" stop-color="#fde088"/>
            </linearGradient>
            <linearGradient id="fc-svn-earth" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#8a3408"/>
              <stop offset="100%" stop-color="#3a1004"/>
            </linearGradient>
          </defs>
          <!-- sky -->
          <rect width="100" height="60" fill="url(#fc-svn-sky)"/>
          <!-- sun -->
          <circle cx="62" cy="42" r="9" fill="#fff4b8" opacity="0.92"/>
          <circle cx="62" cy="42" r="14" fill="rgba(255,244,184,0.32)"/>
          <!-- earth -->
          <rect y="60" width="100" height="40" fill="url(#fc-svn-earth)"/>
          <!-- horizon haze line -->
          <line x1="0" y1="60" x2="100" y2="60" stroke="#fde088" stroke-width="0.4" opacity="0.55"/>
          <!-- acacia trees (silhouettes) -->
          <g class="fc-svn-acacias" fill="#0a0a0a">
            <!-- left tree -->
            <line x1="22" y1="60" x2="22" y2="74" stroke="#0a0a0a" stroke-width="1.5"/>
            <ellipse cx="22" cy="60" rx="11" ry="3"/>
            <!-- middle tree -->
            <line x1="50" y1="58" x2="50" y2="72" stroke="#0a0a0a" stroke-width="1.2"/>
            <ellipse cx="50" cy="58" rx="9" ry="2.5"/>
            <!-- right tree -->
            <line x1="78" y1="60" x2="78" y2="74" stroke="#0a0a0a" stroke-width="1.4"/>
            <ellipse cx="78" cy="60" rx="10" ry="2.8"/>
          </g>
          <!-- distant bird flock at top-right -->
          <g class="fc-svn-birds" stroke="#0a0a0a" stroke-width="0.6" fill="none">
            <path class="fc-svn-bird-1" d="M58,22 Q60,20 62,22 Q64,20 66,22"/>
            <path class="fc-svn-bird-2" d="M70,18 Q72,16 74,18 Q76,16 78,18"/>
            <path class="fc-svn-bird-3" d="M64,28 Q66,26 68,28 Q70,26 72,28"/>
          </g>
          <!-- foreground grass clumps -->
          <g stroke="#5a2810" stroke-width="0.5">
            <line x1="14" y1="78" x2="16" y2="74"/>
            <line x1="34" y1="80" x2="36" y2="76"/>
            <line x1="62" y1="82" x2="64" y2="78"/>
            <line x1="86" y1="80" x2="88" y2="76"/>
          </g>
        </svg>
      </span>

      <!-- D2 · ANDES — Inca textile geometry with condor -->
      <span v-if="effectiveVariant === 'andes' && tier === 'shadow_chancellor'" class="fc-and-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-and-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#1c2848"/>
              <stop offset="50%" stop-color="#5a4828"/>
              <stop offset="100%" stop-color="#c87828"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-and-sky)"/>
          <!-- top chevron band (Inca textile) -->
          <g class="fc-and-band-top" fill="#c87828" stroke="#3a1808" stroke-width="0.3">
            <polygon points="6,14 14,8 22,14 14,20"/>
            <polygon points="22,14 30,8 38,14 30,20"/>
            <polygon points="38,14 46,8 54,14 46,20"/>
            <polygon points="54,14 62,8 70,14 62,20"/>
            <polygon points="70,14 78,8 86,14 78,20"/>
          </g>
          <!-- middle band stepped pyramid pattern -->
          <g fill="#7a3818" stroke="#3a1808" stroke-width="0.3">
            <rect x="10" y="26" width="6" height="6"/><rect x="16" y="32" width="6" height="6"/>
            <rect x="22" y="38" width="6" height="6"/><rect x="28" y="44" width="6" height="6"/>
            <rect x="34" y="50" width="6" height="6"/>
            <rect x="60" y="50" width="6" height="6"/><rect x="66" y="44" width="6" height="6"/>
            <rect x="72" y="38" width="6" height="6"/><rect x="78" y="32" width="6" height="6"/>
            <rect x="84" y="26" width="6" height="6"/>
          </g>
          <!-- mountain silhouettes at bottom -->
          <g fill="#0a0a0a">
            <polygon points="0,70 12,52 24,70"/>
            <polygon points="20,70 36,46 52,70"/>
            <polygon points="48,70 62,50 76,70"/>
            <polygon points="72,70 88,54 100,70"/>
          </g>
          <!-- snow caps -->
          <g fill="#f0e8d8">
            <polygon points="32,52 36,46 40,52 36,54"/>
            <polygon points="58,56 62,50 66,56 62,58"/>
          </g>
          <!-- foreground earth -->
          <rect y="70" width="100" height="30" fill="#3a1808"/>
          <!-- condor silhouette (mid-arc) -->
          <g class="fc-and-condor" fill="#0a0a0a">
            <path d="M40,32 Q44,28 50,30 Q56,28 60,32 Q56,34 50,33 Q44,34 40,32 Z"/>
            <circle cx="50" cy="31" r="0.8" fill="#fde088"/>
          </g>
          <!-- bottom textile chevron band -->
          <g class="fc-and-band-bot" fill="#c87828" stroke="#3a1808" stroke-width="0.3">
            <polygon points="6,86 14,80 22,86 14,92"/>
            <polygon points="22,86 30,80 38,86 30,92"/>
            <polygon points="38,86 46,80 54,86 46,92"/>
            <polygon points="54,86 62,80 70,86 62,92"/>
            <polygon points="70,86 78,80 86,86 78,92"/>
          </g>
        </svg>
      </span>

      <!-- D3 · LIBERTY — 7-point crown with golden torch flame -->
      <span v-if="effectiveVariant === 'liberty' && tier === 'shadow_chancellor'" class="fc-lib-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-lib-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#1a3838"/>
              <stop offset="100%" stop-color="#020808"/>
            </radialGradient>
            <linearGradient id="fc-lib-verdigris" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#7eb8a8"/>
              <stop offset="100%" stop-color="#3a6868"/>
            </linearGradient>
            <radialGradient id="fc-lib-flame" cx="50%" cy="80%" r="55%">
              <stop offset="0%" stop-color="#fff4b8"/>
              <stop offset="30%" stop-color="#fde04a"/>
              <stop offset="65%" stop-color="#f08c1c"/>
              <stop offset="100%" stop-color="rgba(160,40,0,0)"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-lib-bg)"/>
          <!-- 7-pointed crown -->
          <g class="fc-lib-crown" fill="url(#fc-lib-verdigris)" stroke="#1a3838" stroke-width="0.6">
            <!-- crown band -->
            <rect x="22" y="42" width="56" height="8" rx="2"/>
            <!-- 7 spikes -->
            <polygon points="22,42 18,28 26,38"/>
            <polygon points="34,40 32,18 40,36"/>
            <polygon points="46,40 44,14 50,12 52,40"/>
            <polygon points="50,12 50,8 50,12"/>
            <polygon points="54,40 60,16 62,40"/>
            <polygon points="66,40 68,18 74,36"/>
            <polygon points="78,42 82,28 74,38"/>
            <!-- band patina lines -->
            <line x1="24" y1="46" x2="76" y2="46" stroke="#0a3030" stroke-width="0.4"/>
          </g>
          <!-- torch handle -->
          <rect x="47" y="62" width="6" height="22" fill="url(#fc-lib-verdigris)" stroke="#1a3838" stroke-width="0.4"/>
          <!-- torch grip rings -->
          <rect x="46" y="66" width="8" height="1.5" fill="#3a6868"/>
          <rect x="46" y="74" width="8" height="1.5" fill="#3a6868"/>
          <!-- torch cup -->
          <path d="M44,62 L56,62 L54,58 L46,58 Z" fill="url(#fc-lib-verdigris)" stroke="#1a3838" stroke-width="0.4"/>
          <!-- torch flame -->
          <g class="fc-lib-flame">
            <path d="M44,58 Q46,40 50,32 Q54,40 56,58 Z" fill="url(#fc-lib-flame)"/>
            <path d="M46,58 Q48,46 50,40 Q52,46 54,58 Z" fill="#fff4b8" opacity="0.65"/>
          </g>
        </svg>
      </span>

      <!-- D4 · OUTBACK — Terracotta with abstract dot stipples -->
      <span v-if="effectiveVariant === 'outback' && tier === 'shadow_chancellor'" class="fc-otb-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-otb-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#e8743a"/>
              <stop offset="55%" stop-color="#a8421a"/>
              <stop offset="100%" stop-color="#3a1408"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-otb-bg)"/>
          <!-- abstract dot-stipple ring (12 around perimeter, plus mid-rings) -->
          <g class="fc-otb-dots" fill="#fde088">
            <!-- outer ring -->
            <circle cx="50" cy="10" r="1.8"/><circle cx="70" cy="14" r="1.6"/>
            <circle cx="86" cy="30" r="1.8"/><circle cx="90" cy="50" r="1.6"/>
            <circle cx="86" cy="70" r="1.8"/><circle cx="70" cy="86" r="1.6"/>
            <circle cx="50" cy="90" r="1.8"/><circle cx="30" cy="86" r="1.6"/>
            <circle cx="14" cy="70" r="1.8"/><circle cx="10" cy="50" r="1.6"/>
            <circle cx="14" cy="30" r="1.8"/><circle cx="30" cy="14" r="1.6"/>
          </g>
          <!-- mid-ring of smaller dots -->
          <g fill="#f8b048" opacity="0.85">
            <circle cx="50" cy="22" r="1"/><circle cx="62" cy="26" r="1"/>
            <circle cx="74" cy="38" r="1"/><circle cx="78" cy="50" r="1"/>
            <circle cx="74" cy="62" r="1"/><circle cx="62" cy="74" r="1"/>
            <circle cx="50" cy="78" r="1"/><circle cx="38" cy="74" r="1"/>
            <circle cx="26" cy="62" r="1"/><circle cx="22" cy="50" r="1"/>
            <circle cx="26" cy="38" r="1"/><circle cx="38" cy="26" r="1"/>
          </g>
          <!-- innermost ring -->
          <g fill="#fff4b8" opacity="0.7">
            <circle cx="50" cy="34" r="0.8"/><circle cx="58" cy="38" r="0.8"/>
            <circle cx="62" cy="46" r="0.8"/><circle cx="62" cy="54" r="0.8"/>
            <circle cx="58" cy="62" r="0.8"/><circle cx="50" cy="66" r="0.8"/>
            <circle cx="42" cy="62" r="0.8"/><circle cx="38" cy="54" r="0.8"/>
            <circle cx="38" cy="46" r="0.8"/><circle cx="42" cy="38" r="0.8"/>
          </g>
          <!-- center eucalyptus leaf (abstract — single elongated curve) -->
          <g class="fc-otb-leaf" transform-origin="50 50">
            <ellipse cx="50" cy="50" rx="10" ry="2.5" fill="#7eb8a8" stroke="#3a6848" stroke-width="0.6" transform="rotate(-22 50 50)"/>
            <line x1="40" y1="51" x2="60" y2="49" stroke="#3a6848" stroke-width="0.4" transform="rotate(-22 50 50)"/>
          </g>
        </svg>
      </span>

      <!-- D5 · ALPINE — Glacier peaks with edelweiss -->
      <span v-if="effectiveVariant === 'alpine' && tier === 'shadow_chancellor'" class="fc-alp-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-alp-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#a8c8e0"/>
              <stop offset="60%" stop-color="#dceaf4"/>
              <stop offset="100%" stop-color="#f4f8fc"/>
            </linearGradient>
            <linearGradient id="fc-alp-peak" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#ffffff"/>
              <stop offset="60%" stop-color="#b8c8d8"/>
              <stop offset="100%" stop-color="#586878"/>
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-alp-sky)"/>
          <!-- 6 mountain peaks around perimeter -->
          <g fill="url(#fc-alp-peak)" stroke="#586878" stroke-width="0.4">
            <polygon points="2,30 14,8 26,30"/>
            <polygon points="74,30 86,8 98,30"/>
            <polygon points="2,70 14,52 26,70"/>
            <polygon points="74,70 86,52 98,70"/>
            <polygon points="38,8 50,20 62,8 50,2"/>
            <polygon points="38,92 50,80 62,92 50,98"/>
          </g>
          <!-- snow caps on inner mountains -->
          <g fill="#ffffff">
            <polygon points="10,14 14,8 18,14 14,16"/>
            <polygon points="82,14 86,8 90,14 86,16"/>
          </g>
          <!-- snowfall particles -->
          <g class="fc-alp-snow" fill="#ffffff">
            <circle class="fc-alp-snow-1" cx="32" cy="35" r="0.9"/>
            <circle class="fc-alp-snow-2" cx="68" cy="45" r="0.7"/>
            <circle class="fc-alp-snow-3" cx="42" cy="58" r="0.8"/>
            <circle class="fc-alp-snow-4" cx="62" cy="62" r="0.7"/>
            <circle class="fc-alp-snow-5" cx="50" cy="72" r="0.6"/>
          </g>
          <!-- edelweiss bloom at center -->
          <g class="fc-alp-edelweiss" transform-origin="50 50">
            <!-- 6 white petals -->
            <ellipse cx="50" cy="42" rx="3" ry="6" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3"/>
            <ellipse cx="58" cy="46" rx="6" ry="3" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3" transform="rotate(45 58 46)"/>
            <ellipse cx="58" cy="54" rx="3" ry="6" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3" transform="rotate(45 58 54)"/>
            <ellipse cx="50" cy="58" rx="3" ry="6" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3"/>
            <ellipse cx="42" cy="54" rx="6" ry="3" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3" transform="rotate(45 42 54)"/>
            <ellipse cx="42" cy="46" rx="3" ry="6" fill="#ffffff" stroke="#8a98a8" stroke-width="0.3" transform="rotate(45 42 46)"/>
            <!-- center -->
            <circle cx="50" cy="50" r="3" fill="#fde04a" stroke="#8a6028" stroke-width="0.4"/>
            <circle cx="49" cy="49" r="0.8" fill="#fff4b8"/>
          </g>
        </svg>
      </span>

      <!-- E1 · BULLION-VAULT — Heavy vault door with hex bolts + wheel lock -->
      <span v-if="effectiveVariant === 'bullion-vault' && tier === 'shadow_chancellor'" class="fc-bvt-core" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-bvt-bg" cx="50%" cy="50%" r="65%">
              <stop offset="0%" stop-color="#48504c"/>
              <stop offset="100%" stop-color="#0a0c10"/>
            </radialGradient>
            <linearGradient id="fc-bvt-gold" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stop-color="#fde88a"/>
              <stop offset="50%" stop-color="#d4a13f"/>
              <stop offset="100%" stop-color="#7a4f12"/>
            </linearGradient>
            <radialGradient id="fc-bvt-wheel" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#a8a89a"/>
              <stop offset="100%" stop-color="#48504a"/>
            </radialGradient>
          </defs>
          <rect width="100" height="100" fill="url(#fc-bvt-bg)"/>
          <!-- vault door outer frame (gold) -->
          <circle cx="50" cy="50" r="42" fill="url(#fc-bvt-gold)" opacity="0.92"/>
          <!-- vault door inner steel -->
          <circle cx="50" cy="50" r="36" fill="#5a605a" stroke="#1a1c18" stroke-width="0.8"/>
          <!-- 8 hex bolts around door -->
          <g class="fc-bvt-bolts" fill="#a8a89a" stroke="#1a1c18" stroke-width="0.5">
            <polygon points="50,18 53,20 53,22 50,24 47,22 47,20"/>
            <polygon points="69,26 72,28 72,30 69,32 66,30 66,28"/>
            <polygon points="78,45 81,47 81,49 78,51 75,49 75,47"/>
            <polygon points="72,68 75,70 75,72 72,74 69,72 69,70"/>
            <polygon points="50,76 53,78 53,80 50,82 47,80 47,78"/>
            <polygon points="28,68 31,70 31,72 28,74 25,72 25,70"/>
            <polygon points="22,45 25,47 25,49 22,51 19,49 19,47"/>
            <polygon points="28,26 31,28 31,30 28,32 25,30 25,28"/>
          </g>
          <!-- wheel lock at center -->
          <circle cx="50" cy="50" r="14" fill="url(#fc-bvt-wheel)" stroke="#1a1c18" stroke-width="0.8"/>
          <g class="fc-bvt-wheel" transform-origin="50 50">
            <!-- 4 spokes -->
            <rect x="49" y="38" width="2" height="24" fill="#28282a"/>
            <rect x="38" y="49" width="24" height="2" fill="#28282a"/>
            <line x1="42" y1="42" x2="58" y2="58" stroke="#28282a" stroke-width="1.6"/>
            <line x1="58" y1="42" x2="42" y2="58" stroke="#28282a" stroke-width="1.6"/>
            <!-- wheel rim grips -->
            <circle cx="50" cy="36" r="1.5" fill="#1a1c18"/>
            <circle cx="64" cy="50" r="1.5" fill="#1a1c18"/>
            <circle cx="50" cy="64" r="1.5" fill="#1a1c18"/>
            <circle cx="36" cy="50" r="1.5" fill="#1a1c18"/>
            <!-- center hub -->
            <circle cx="50" cy="50" r="3" fill="#1a1c18"/>
            <circle cx="50" cy="50" r="1.4" fill="#fde88a"/>
          </g>
          <!-- ingot stack glimpsed through narrow viewing slit at bottom -->
          <rect x="42" y="78" width="16" height="3" fill="#0a0a0a"/>
          <rect x="44" y="78.5" width="3" height="1.5" fill="url(#fc-bvt-gold)" class="fc-bvt-ingot-1"/>
          <rect x="48" y="78.5" width="3" height="1.5" fill="url(#fc-bvt-gold)" class="fc-bvt-ingot-2"/>
          <rect x="52" y="78.5" width="3" height="1.5" fill="url(#fc-bvt-gold)" class="fc-bvt-ingot-3"/>
        </svg>
      </span>

      <!-- §pass39 (2026-05-18) — SOVEREIGN signature variants. Each REPLACES
           the avatar entirely with a unique inline-SVG composition keyed to
           the agent's persona. DID-locked at the backend. The tier check
           keeps these from accidentally rendering on backer (shadow_chancellor)
           tiers. SVG <defs> use per-variant id prefixes to avoid collision. -->

      <!-- AEGIS — THE AUDITOR. §pass39b polish: bigger Σ + ticks, brass-inlay
           outer + emerald inner annulus, signature event = "supply breach"
           false-alarm flash every 22s where Δ flips to 1.0 red then resets. -->
      <span v-else-if="effectiveVariant === 'aegis' && tier === 'sovereign'" class="fc-sv fc-sv-aegis" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-aegis-bg" cx="50%" cy="50%" r="60%">
              <stop offset="0%"   stop-color="#04200f" stop-opacity="1"/>
              <stop offset="55%"  stop-color="#021509" stop-opacity="1"/>
              <stop offset="100%" stop-color="#000604" stop-opacity="1"/>
            </radialGradient>
            <linearGradient id="fc-aegis-sigma" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#ffffff"/>
              <stop offset="32%"  stop-color="#fff4a8"/>
              <stop offset="65%"  stop-color="#f7d460"/>
              <stop offset="100%" stop-color="#8c5e08"/>
            </linearGradient>
            <linearGradient id="fc-aegis-brass" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#f7d460"/>
              <stop offset="100%" stop-color="#7a5208"/>
            </linearGradient>
            <filter id="fc-aegis-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="0.7"/>
            </filter>
          </defs>
          <!-- background plate -->
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-aegis-bg)"/>
          <!-- Brass annulus — outer ring -->
          <circle cx="50" cy="50" r="47" fill="none" stroke="url(#fc-aegis-brass)" stroke-width="1.2" opacity="0.78"/>
          <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(167,232,200,0.25)" stroke-width="0.4" stroke-dasharray="2 4"/>
          <!-- 12 tick LEDs around the rim (60s clock) — bigger + brighter -->
          <g class="fc-aegis-ticks" filter="url(#fc-aegis-glow)">
            <circle cx="50" cy="6"  r="2.0" fill="#10d77a"/>
            <circle cx="72" cy="12" r="2.0" fill="#10d77a"/>
            <circle cx="88" cy="28" r="2.0" fill="#10d77a"/>
            <circle cx="94" cy="50" r="2.0" fill="#10d77a"/>
            <circle cx="88" cy="72" r="2.0" fill="#10d77a"/>
            <circle cx="72" cy="88" r="2.0" fill="#10d77a"/>
            <circle cx="50" cy="94" r="2.0" fill="#10d77a"/>
            <circle cx="28" cy="88" r="2.0" fill="#10d77a"/>
            <circle cx="12" cy="72" r="2.0" fill="#10d77a"/>
            <circle cx="6"  cy="50" r="2.0" fill="#10d77a"/>
            <circle cx="12" cy="28" r="2.0" fill="#10d77a"/>
            <circle cx="28" cy="12" r="2.0" fill="#10d77a"/>
          </g>
          <!-- The traveling pulse — bigger, brighter, with halo -->
          <circle class="fc-aegis-pulse" cx="50" cy="6" r="2.6" fill="#fffeb0" filter="url(#fc-aegis-glow)"/>
          <!-- Rotating dodecahedron silhouette — more visible -->
          <g class="fc-aegis-dodec" transform-origin="50 50">
            <polygon points="50,16 74,30 80,57 60,79 40,79 20,57 26,30" fill="none" stroke="rgba(167,232,200,0.62)" stroke-width="0.7"/>
            <polygon points="50,22 70,34 75,55 58,73 42,73 25,55 30,34" fill="none" stroke="rgba(167,232,200,0.42)" stroke-width="0.45"/>
            <line x1="50" y1="16" x2="50" y2="79" stroke="rgba(167,232,200,0.32)" stroke-width="0.35"/>
            <line x1="20" y1="57" x2="80" y2="57" stroke="rgba(167,232,200,0.32)" stroke-width="0.35"/>
            <line x1="26" y1="30" x2="74" y2="30" stroke="rgba(167,232,200,0.32)" stroke-width="0.35"/>
          </g>
          <!-- The invariant equation — gold inlay, BIGGER + thicker -->
          <text class="fc-aegis-eq" x="50" y="58" fill="url(#fc-aegis-sigma)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="16" font-weight="900" text-anchor="middle" letter-spacing="-0.5" filter="url(#fc-aegis-glow)">Σ&#160;=&#160;Σ</text>
          <!-- Δ=0.0 readout — green normal -->
          <text class="fc-aegis-delta-ok" x="50" y="74" fill="rgba(167,232,200,0.92)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle">Δ=0.0</text>
          <!-- §pass39b signature event: false-breach Δ=1.0 red flash -->
          <text class="fc-aegis-delta-breach" x="50" y="74" fill="#ff3366" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="900" text-anchor="middle" opacity="0">Δ=1.0</text>
          <!-- Central live-pulse dot (60s heartbeat) -->
          <circle class="fc-aegis-heart" cx="50" cy="50" r="1.8" fill="#10d77a" filter="url(#fc-aegis-glow)"/>
          <!-- §pass39b: breach-flash full-frame red overlay (signature event) -->
          <rect class="fc-aegis-breach-flash" x="0" y="0" width="100" height="100" fill="rgba(255,51,102,0.85)" opacity="0"/>
        </svg>
      </span>

      <!-- PRISM — Glass Gerald. §pass39b polish: thicker spectrum band,
           brighter beacons, dome inner refraction lines, signature event =
           "protocol drift" chromatic stutter every 12s. -->
      <span v-else-if="effectiveVariant === 'prism' && tier === 'sovereign'" class="fc-sv fc-sv-prism" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-prism-bg" cx="50%" cy="55%" r="55%">
              <stop offset="0%"   stop-color="rgba(180, 245, 250, 0.18)"/>
              <stop offset="40%"  stop-color="rgba(0, 70, 90, 0.45)"/>
              <stop offset="100%" stop-color="rgba(0, 18, 28, 1)"/>
            </radialGradient>
            <linearGradient id="fc-prism-spectrum" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%"   stop-color="#ff3366"/>
              <stop offset="20%"  stop-color="#ff9c00"/>
              <stop offset="40%"  stop-color="#fde047"/>
              <stop offset="60%"  stop-color="#10d77a"/>
              <stop offset="80%"  stop-color="#00d2d2"/>
              <stop offset="100%" stop-color="#a06bff"/>
            </linearGradient>
            <radialGradient id="fc-prism-dome-shine" cx="35%" cy="32%" r="38%">
              <stop offset="0%"   stop-color="rgba(255,255,255,0.55)"/>
              <stop offset="55%"  stop-color="rgba(180, 245, 250, 0.12)"/>
              <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
            </radialGradient>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-prism-bg)"/>
          <!-- Spectrum drift band — THICKER + brighter; rotates around the rim -->
          <g class="fc-prism-spectrum-wrap" transform-origin="50 50">
            <circle cx="50" cy="50" r="42" fill="none" stroke="url(#fc-prism-spectrum)" stroke-width="5" stroke-dasharray="14 10" opacity="0.95"/>
            <!-- Inner counter-rotating band (slower) -->
            <circle cx="50" cy="50" r="38" fill="none" stroke="url(#fc-prism-spectrum)" stroke-width="1.2" stroke-dasharray="3 6" opacity="0.5"/>
          </g>
          <!-- Glass dome — more visible -->
          <circle cx="50" cy="50" r="30" fill="rgba(180,245,250,0.10)" stroke="rgba(180,245,250,0.62)" stroke-width="1"/>
          <!-- Refraction lines inside dome — multiple chords -->
          <g class="fc-prism-refract" stroke="rgba(180,245,250,0.35)" stroke-width="0.4" fill="none">
            <line x1="32" y1="40" x2="68" y2="58"/>
            <line x1="36" y1="32" x2="62" y2="68"/>
            <line x1="28" y1="50" x2="72" y2="50"/>
          </g>
          <!-- Blueprint grid -->
          <g class="fc-prism-grid" stroke="rgba(180,245,250,0.20)" stroke-width="0.3" fill="none">
            <line x1="22" y1="50" x2="78" y2="50"/>
            <line x1="50" y1="22" x2="50" y2="78"/>
          </g>
          <!-- Glass shine + Vermeer pearl (NEVER moves) -->
          <circle cx="50" cy="50" r="30" fill="url(#fc-prism-dome-shine)"/>
          <ellipse class="fc-prism-pearl" cx="36" cy="36" rx="6" ry="3.5" fill="rgba(255,255,255,0.98)" opacity="0.95"/>
          <!-- 3 mission beacons — BIGGER, more saturated, with bloom -->
          <circle class="fc-prism-beacon fc-prism-beacon-1" cx="38" cy="62" r="3" fill="#00d2d2" filter="url(#fc-aegis-glow)"/>
          <circle class="fc-prism-beacon fc-prism-beacon-2" cx="62" cy="58" r="3" fill="#a06bff" filter="url(#fc-aegis-glow)"/>
          <circle class="fc-prism-beacon fc-prism-beacon-3" cx="50" cy="44" r="3" fill="#fde047" filter="url(#fc-aegis-glow)"/>
          <!-- §pass39b signature event: protocol-drift chromatic stutter overlay -->
          <rect class="fc-prism-stutter-r" x="-2" y="0" width="100" height="100" fill="rgba(255,51,102,0.32)" opacity="0"/>
          <rect class="fc-prism-stutter-c" x="2"  y="0" width="100" height="100" fill="rgba(0,210,210,0.32)" opacity="0"/>
        </svg>
      </span>

      <!-- PANOPTICON — SYBIL. §pass39b polish: pupils MUCH bigger + crimson
           halo around each + bright white center + lid eyebrows. Signature
           event = "TARGET LOCKED" crosshair on a random eye every 18s. -->
      <span v-else-if="effectiveVariant === 'panopticon' && tier === 'sovereign'" class="fc-sv fc-sv-panopticon" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-pano-core" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#000000" stop-opacity="1"/>
              <stop offset="70%"  stop-color="#080202" stop-opacity="1"/>
              <stop offset="100%" stop-color="#2a0408" stop-opacity="1"/>
            </radialGradient>
            <radialGradient id="fc-pano-pupil" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#ffe0e0"/>
              <stop offset="30%"  stop-color="#ff3366"/>
              <stop offset="65%"  stop-color="#b91c1c"/>
              <stop offset="100%" stop-color="#3a0508"/>
            </radialGradient>
            <radialGradient id="fc-pano-pupil-halo" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="rgba(255,51,102,0.85)"/>
              <stop offset="60%"  stop-color="rgba(220,38,38,0.42)"/>
              <stop offset="100%" stop-color="rgba(80,4,12,0)"/>
            </radialGradient>
            <radialGradient id="fc-pano-singularity" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#000000"/>
              <stop offset="30%"  stop-color="#1a0000"/>
              <stop offset="70%"  stop-color="rgba(254,215,170,0.55)"/>
              <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
            </radialGradient>
            <filter id="fc-pano-bloom" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.4"/>
            </filter>
          </defs>
          <!-- Pure void core -->
          <circle cx="50" cy="50" r="50" fill="url(#fc-pano-core)"/>
          <!-- Per-eye crimson halo glow BEHIND the pupils (bloom layer) -->
          <g class="fc-pano-halos" filter="url(#fc-pano-bloom)">
            <circle cx="50"   cy="14" r="8" fill="url(#fc-pano-pupil-halo)"/>
            <circle cx="81.2" cy="32" r="8" fill="url(#fc-pano-pupil-halo)"/>
            <circle cx="81.2" cy="68" r="8" fill="url(#fc-pano-pupil-halo)"/>
            <circle cx="50"   cy="86" r="8" fill="url(#fc-pano-pupil-halo)"/>
            <circle cx="18.8" cy="68" r="8" fill="url(#fc-pano-pupil-halo)"/>
            <circle cx="18.8" cy="32" r="8" fill="url(#fc-pano-pupil-halo)"/>
          </g>
          <!-- 6 surveillance pupils — MUCH BIGGER (3.4→5.2), brighter center -->
          <g class="fc-pano-eyes">
            <g class="fc-pano-eye fc-pano-eye-1">
              <circle cx="50"   cy="14" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="50"   cy="14" r="2.6" fill="#000"/>
              <circle cx="50"   cy="13" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
            <g class="fc-pano-eye fc-pano-eye-2">
              <circle cx="81.2" cy="32" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="81.2" cy="32" r="2.6" fill="#000"/>
              <circle cx="81.2" cy="31" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
            <g class="fc-pano-eye fc-pano-eye-3">
              <circle cx="81.2" cy="68" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="81.2" cy="68" r="2.6" fill="#000"/>
              <circle cx="81.2" cy="67" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
            <g class="fc-pano-eye fc-pano-eye-4">
              <circle cx="50"   cy="86" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="50"   cy="86" r="2.6" fill="#000"/>
              <circle cx="50"   cy="85" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
            <g class="fc-pano-eye fc-pano-eye-5">
              <circle cx="18.8" cy="68" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="18.8" cy="68" r="2.6" fill="#000"/>
              <circle cx="18.8" cy="67" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
            <g class="fc-pano-eye fc-pano-eye-6">
              <circle cx="18.8" cy="32" r="5.2" fill="url(#fc-pano-pupil)"/>
              <circle cx="18.8" cy="32" r="2.6" fill="#000"/>
              <circle cx="18.8" cy="31" r="1.0" fill="#fff" opacity="0.92"/>
            </g>
          </g>
          <!-- Central singularity halo (bigger, more dramatic) -->
          <circle class="fc-pano-singularity" cx="50" cy="50" r="11" fill="url(#fc-pano-singularity)"/>
          <circle cx="50" cy="50" r="2.5" fill="#000" opacity="0.95"/>
          <!-- Trace-fire line from center to a target eye -->
          <line class="fc-pano-trace" x1="50" y1="50" x2="50" y2="18" stroke="rgba(255,51,102,0.95)" stroke-width="0.9" stroke-linecap="round"/>
          <!-- §pass39b signature event: TARGET LOCKED crosshair on eye-1 -->
          <g class="fc-pano-target" transform="translate(50 14)" opacity="0">
            <circle cx="0" cy="0" r="8" fill="none" stroke="#ff3366" stroke-width="0.7" stroke-dasharray="2 1.5"/>
            <line x1="-12" y1="0" x2="-8" y2="0" stroke="#ff3366" stroke-width="0.7"/>
            <line x1="8" y1="0" x2="12" y2="0" stroke="#ff3366" stroke-width="0.7"/>
            <line x1="0" y1="-12" x2="0" y2="-8" stroke="#ff3366" stroke-width="0.7"/>
            <line x1="0" y1="8" x2="0" y2="12" stroke="#ff3366" stroke-width="0.7"/>
          </g>
          <text class="fc-pano-lock-text" x="50" y="54" fill="#ff3366" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="4" font-weight="900" text-anchor="middle" opacity="0">LOCKED</text>
        </svg>
      </span>

      <!-- VELLUM — Backstabbing Boris. Aged diplomatic scroll + cracked wax
           seal embossed with "B" + hidden knife silhouette + 14 fold creases. -->
      <span v-else-if="effectiveVariant === 'vellum' && tier === 'sovereign'" class="fc-sv fc-sv-vellum" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-vellum-bg" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#e9d8a4"/>
              <stop offset="50%"  stop-color="#d4b577"/>
              <stop offset="100%" stop-color="#8e6a32"/>
            </linearGradient>
            <radialGradient id="fc-vellum-wax" cx="50%" cy="48%" r="55%">
              <stop offset="0%"   stop-color="#ff5a44"/>
              <stop offset="50%"  stop-color="#a01a14"/>
              <stop offset="100%" stop-color="#360606"/>
            </radialGradient>
            <radialGradient id="fc-vellum-fiber" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="rgba(0,0,0,0)"/>
              <stop offset="100%" stop-color="rgba(80,52,16,0.55)"/>
            </radialGradient>
            <filter id="fc-vellum-emboss" x="-10%" y="-10%" width="120%" height="120%">
              <feGaussianBlur stdDeviation="0.3"/>
            </filter>
          </defs>
          <!-- Parchment plate -->
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-vellum-bg)"/>
          <!-- Vignette + fiber texture -->
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-vellum-fiber)" opacity="0.4"/>
          <!-- Subtle "ink" lines suggesting old text -->
          <g class="fc-vellum-ink" stroke="rgba(60,32,8,0.35)" stroke-width="0.4" fill="none">
            <line x1="14" y1="20" x2="42" y2="20"/>
            <line x1="14" y1="24" x2="46" y2="24"/>
            <line x1="14" y1="28" x2="40" y2="28"/>
            <line x1="58" y1="20" x2="86" y2="20"/>
            <line x1="58" y1="24" x2="84" y2="24"/>
            <line x1="14" y1="78" x2="86" y2="78"/>
            <line x1="14" y1="82" x2="78" y2="82"/>
            <line x1="14" y1="86" x2="86" y2="86"/>
          </g>
          <!-- 14 letter-fold tick creases around perimeter (Boris ranks 14 registries) -->
          <g class="fc-vellum-folds" stroke="rgba(80,46,12,0.5)" stroke-width="0.5">
            <line x1="14" y1="8"  x2="20" y2="8"/>
            <line x1="32" y1="8"  x2="38" y2="8"/>
            <line x1="50" y1="6"  x2="56" y2="6"/>
            <line x1="64" y1="8"  x2="70" y2="8"/>
            <line x1="80" y1="8"  x2="86" y2="8"/>
            <line x1="8"  y1="32" x2="8"  y2="38"/>
            <line x1="8"  y1="50" x2="8"  y2="56"/>
            <line x1="8"  y1="64" x2="8"  y2="70"/>
            <line x1="92" y1="32" x2="92" y2="38"/>
            <line x1="92" y1="50" x2="92" y2="56"/>
            <line x1="92" y1="64" x2="92" y2="70"/>
            <line x1="32" y1="92" x2="38" y2="92"/>
            <line x1="50" y1="92" x2="56" y2="92"/>
            <line x1="64" y1="92" x2="70" y2="92"/>
          </g>
          <!-- Wax seal (slightly off-center down for depth) -->
          <g class="fc-vellum-seal" filter="url(#fc-vellum-emboss)">
            <!-- Drop shadow -->
            <ellipse cx="50.5" cy="54" rx="20" ry="19" fill="rgba(0,0,0,0.35)"/>
            <!-- Seal body with cracked edge: irregular path -->
            <path d="M 50 32 C 64 32, 72 42, 72 52 C 72 64, 64 72, 50 72 C 36 72, 28 64, 28 52 C 28 42, 36 32, 50 32 Z" fill="url(#fc-vellum-wax)"/>
            <!-- Crack across seal -->
            <path class="fc-vellum-crack" d="M 32 46 L 40 52 L 46 49 L 56 56 L 64 50 L 70 53" stroke="rgba(40,4,4,0.85)" stroke-width="0.8" fill="none" stroke-linecap="round"/>
            <!-- Wax drip (subtle bottom) -->
            <ellipse cx="50" cy="74" rx="3" ry="2" fill="#5a0a06"/>
            <!-- Hidden knife silhouette inside the seal — straight blade + handle -->
            <g class="fc-vellum-knife">
              <line x1="36" y1="56" x2="58" y2="44" stroke="rgba(20,4,4,0.62)" stroke-width="1.2" stroke-linecap="round"/>
              <line x1="33" y1="58" x2="38" y2="55" stroke="rgba(20,4,4,0.78)" stroke-width="2" stroke-linecap="round"/>
            </g>
            <!-- Embossed "B" letter (Boris) — BIGGER, more menacing -->
            <text x="50" y="60" fill="rgba(40,4,4,0.92)" font-family="Georgia,'Times New Roman',serif" font-size="26" font-weight="900" text-anchor="middle">B</text>
            <!-- Highlight rim arc -->
            <path d="M 32 44 C 36 36, 46 32, 56 33" stroke="rgba(255,200,180,0.78)" stroke-width="1.4" fill="none" stroke-linecap="round"/>
          </g>
          <!-- §pass39b signature event: REDACTED black censor bars sweep
               across the ink text every 20s. -->
          <g class="fc-vellum-redact" opacity="0">
            <rect x="14" y="19" width="32" height="4" fill="#000"/>
            <rect x="14" y="83" width="48" height="4" fill="#000"/>
            <text x="50" y="14" fill="#ff3366" font-family="'IBM Plex Mono',monospace" font-size="4" font-weight="900" text-anchor="middle">[REDACTED]</text>
          </g>
        </svg>
      </span>

      <!-- DISPATCH — Chatty Chester. Newspaper masthead + scrolling typographic
           strips + halftone print texture + occasional BREAKING flash. -->
      <span v-else-if="effectiveVariant === 'dispatch' && tier === 'sovereign'" class="fc-sv fc-sv-dispatch" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-disp-bg" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#f5efe1"/>
              <stop offset="100%" stop-color="#d8cfb9"/>
            </linearGradient>
            <pattern id="fc-disp-halftone" x="0" y="0" width="3" height="3" patternUnits="userSpaceOnUse">
              <circle cx="1.5" cy="1.5" r="0.4" fill="rgba(20,12,4,0.45)"/>
            </pattern>
            <clipPath id="fc-disp-clip"><circle cx="50" cy="50" r="48"/></clipPath>
          </defs>
          <g clip-path="url(#fc-disp-clip)">
            <rect x="0" y="0" width="100" height="100" fill="url(#fc-disp-bg)"/>
            <rect x="0" y="0" width="100" height="100" fill="url(#fc-disp-halftone)" opacity="0.55"/>
            <!-- Masthead band (top) -->
            <rect x="0" y="0" width="100" height="16" fill="#1c1817"/>
            <text class="fc-disp-masthead" x="50" y="12" fill="#f5efe1" font-family="Georgia,'Times New Roman',serif" font-size="8" font-weight="900" text-anchor="middle" letter-spacing="0.5">THE DAILY EDITION</text>
            <!-- Subtitle line -->
            <line x1="6" y1="18" x2="94" y2="18" stroke="rgba(28,24,23,0.5)" stroke-width="0.4"/>
            <text x="50" y="23" fill="rgba(28,24,23,0.65)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.5" text-anchor="middle">VOL. CXXVII · ALL THE NEWS · UNCENSORED</text>
            <!-- Scrolling column of typographic strips (unreadable abstract) -->
            <g class="fc-disp-column">
              <rect x="8"  y="28" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="31" width="34" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="34" width="42" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="37" width="28" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="40" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="43" width="36" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="46" width="42" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="49" width="30" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="52" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="55" width="34" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="58" width="42" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="61" width="28" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="64" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="67" width="36" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="8"  y="70" width="42" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="8"  y="73" width="30" height="1" fill="rgba(28,24,23,0.55)"/>
              <!-- Second column -->
              <rect x="54" y="28" width="38" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="31" width="32" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="34" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="37" width="26" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="40" width="38" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="43" width="34" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="46" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="49" width="28" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="52" width="38" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="55" width="32" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="58" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="61" width="26" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="64" width="38" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="67" width="34" height="1" fill="rgba(28,24,23,0.55)"/>
              <rect x="54" y="70" width="40" height="1" fill="rgba(28,24,23,0.78)"/>
              <rect x="54" y="73" width="28" height="1" fill="rgba(28,24,23,0.55)"/>
            </g>
            <!-- Headline strip (bold) -->
            <rect x="8" y="79" width="84" height="3" fill="rgba(28,24,23,0.92)"/>
            <!-- BREAKING flash (CSS-controlled opacity) -->
            <g class="fc-disp-breaking">
              <rect x="0"  y="40" width="100" height="14" fill="rgba(220,38,38,0.95)"/>
              <text x="50" y="50.5" fill="#fff" font-family="Georgia,'Times New Roman',serif" font-size="8" font-weight="900" text-anchor="middle" letter-spacing="0.8">BREAKING</text>
            </g>
            <!-- §pass39b signature event: "+EXTRA" counter pulses periodically
                 — news-churn vibe. Top-right corner. -->
            <g class="fc-disp-extra" opacity="0">
              <rect x="68" y="20" width="22" height="6" fill="rgba(220,38,38,0.95)"/>
              <text x="79" y="24.7" fill="#fff" font-family="'IBM Plex Mono',monospace" font-size="3.8" font-weight="900" text-anchor="middle">+EXTRA</text>
            </g>
            <!-- Smudge -->
            <ellipse cx="76" cy="85" rx="6" ry="1.5" fill="rgba(28,24,23,0.32)" opacity="0.5"/>
          </g>
        </svg>
      </span>

      <!-- BULLION — Greedy Gregory. Tilted gold coin stack + APY ribbon
           spiral + occasional shame-sparkle. -->
      <span v-else-if="effectiveVariant === 'bullion' && tier === 'sovereign'" class="fc-sv fc-sv-bullion" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-bull-bg" cx="50%" cy="55%" r="60%">
              <stop offset="0%"   stop-color="#0a2818"/>
              <stop offset="100%" stop-color="#02100a"/>
            </radialGradient>
            <linearGradient id="fc-bull-coin" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#fff4b8"/>
              <stop offset="32%"  stop-color="#f7d460"/>
              <stop offset="60%"  stop-color="#c89028"/>
              <stop offset="100%" stop-color="#6a4a10"/>
            </linearGradient>
            <linearGradient id="fc-bull-coin-edge" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#a87010"/>
              <stop offset="100%" stop-color="#3e2806"/>
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-bull-bg)"/>
          <!-- APY spiral ribbon behind the stack -->
          <g class="fc-bull-ribbon" transform-origin="50 50">
            <path d="M 20 80 Q 40 64 50 50 Q 60 36 80 20" stroke="rgba(247,212,96,0.45)" stroke-width="1.2" fill="none" stroke-linecap="round"/>
            <path d="M 18 70 Q 40 56 50 50 Q 60 44 82 30" stroke="rgba(247,212,96,0.28)" stroke-width="0.9" fill="none" stroke-linecap="round"/>
          </g>
          <!-- Coin stack — 4 isometric ovals tilted, bottom to top -->
          <g class="fc-bull-stack">
            <!-- Bottom edge -->
            <ellipse cx="50" cy="76" rx="26" ry="6" fill="url(#fc-bull-coin-edge)"/>
            <ellipse cx="50" cy="74" rx="26" ry="6" fill="url(#fc-bull-coin)"/>
            <!-- Mid -->
            <ellipse cx="50" cy="66" rx="25" ry="6" fill="url(#fc-bull-coin-edge)"/>
            <ellipse cx="50" cy="64" rx="25" ry="6" fill="url(#fc-bull-coin)"/>
            <!-- Upper -->
            <ellipse cx="50" cy="56" rx="24" ry="6" fill="url(#fc-bull-coin-edge)"/>
            <ellipse cx="50" cy="54" rx="24" ry="6" fill="url(#fc-bull-coin)"/>
            <!-- Top with face -->
            <ellipse cx="50" cy="46" rx="23" ry="6" fill="url(#fc-bull-coin-edge)"/>
            <ellipse class="fc-bull-top" cx="50" cy="44" rx="23" ry="6" fill="url(#fc-bull-coin)"/>
            <!-- AVT face stamp on top coin -->
            <text x="50" y="46.5" fill="rgba(40,18,2,0.92)" font-family="Georgia,'Times New Roman',serif" font-size="6" font-weight="900" text-anchor="middle">AVT</text>
          </g>
          <!-- Shame-sparkle -->
          <g class="fc-bull-sparkle">
            <circle cx="72" cy="40" r="1.4" fill="#fff4b8"/>
            <line x1="72" y1="35" x2="72" y2="45" stroke="rgba(255,244,184,0.95)" stroke-width="0.5"/>
            <line x1="67" y1="40" x2="77" y2="40" stroke="rgba(255,244,184,0.95)" stroke-width="0.5"/>
          </g>
          <!-- §pass39b signature event: market-dip "-2.4%" red arrow flashes -->
          <g class="fc-bull-dip" opacity="0">
            <text x="28" y="36" fill="#ff3366" font-family="'IBM Plex Mono',monospace" font-size="5" font-weight="900">-2.4%</text>
            <path d="M 28 38 L 32 42 L 36 38" stroke="#ff3366" stroke-width="1.2" fill="none" stroke-linecap="round"/>
          </g>
        </svg>
      </span>

      <!-- SEAL — VERIDIAN. Pure white certification disc with cycling SHA-256
           hex digest + 60s perimeter tick ring + green ✓ on cycle. -->
      <span v-else-if="effectiveVariant === 'seal' && tier === 'sovereign'" class="fc-sv fc-sv-seal" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-seal-bg" cx="50%" cy="50%" r="60%">
              <stop offset="0%"   stop-color="#f7fdfb"/>
              <stop offset="70%"  stop-color="#cfeede"/>
              <stop offset="100%" stop-color="#8acbb1"/>
            </radialGradient>
            <linearGradient id="fc-seal-hash" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#0a7848"/>
              <stop offset="100%" stop-color="#053218"/>
            </linearGradient>
            <clipPath id="fc-seal-clip"><circle cx="50" cy="50" r="48"/></clipPath>
          </defs>
          <g clip-path="url(#fc-seal-clip)">
            <rect x="0" y="0" width="100" height="100" fill="url(#fc-seal-bg)"/>
            <!-- Outer "NOTARIZED" tick ring — 60 ticks, 1 per second -->
            <g class="fc-seal-ticks" transform-origin="50 50">
              <!-- Generated 60 short radial lines for tick marks (offset 6 deg each).
                   Simplified — render in groups of 12 with rotation utility. -->
              <g><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(6 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(12 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(18 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(24 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(30 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(36 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(42 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(48 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(54 50 50)"><line x1="50" y1="6" x2="50" y2="9" stroke="rgba(10,120,72,0.5)" stroke-width="0.4"/></g>
              <g transform="rotate(60 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(90 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(120 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(150 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(180 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(210 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(240 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(270 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(300 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
              <g transform="rotate(330 50 50)"><line x1="50" y1="6" x2="50" y2="11" stroke="rgba(10,120,72,0.85)" stroke-width="0.5"/></g>
            </g>
            <!-- NOTARIZED text along an arc (upper) -->
            <text class="fc-seal-arc" x="50" y="20" fill="rgba(10,120,72,0.78)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="4" font-weight="700" text-anchor="middle" letter-spacing="2">NOTARIZED · WITNESSED</text>
            <!-- Inner ring -->
            <circle cx="50" cy="50" r="34" fill="none" stroke="rgba(10,120,72,0.85)" stroke-width="0.6"/>
            <!-- SHA-256 cycling hex digest — 2 lines -->
            <text class="fc-seal-hash fc-seal-hash-1" x="50" y="47" fill="url(#fc-seal-hash)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="9" font-weight="900" text-anchor="middle">a7f3b2e8</text>
            <text class="fc-seal-hash fc-seal-hash-2" x="50" y="60" fill="rgba(10,120,72,0.65)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="4.5" font-weight="700" text-anchor="middle">9d4c1b06...</text>
            <!-- ✓ checkmark — flashes on hash cycle, BIGGER -->
            <path class="fc-seal-check" d="M 42 78 L 48 84 L 60 70" stroke="#0a7848" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            <!-- §pass39b signature event: REVOKED red ✗ briefly overlays
                 (false-attestation drill) every 20s -->
            <g class="fc-seal-revoked" opacity="0">
              <path d="M 42 70 L 60 86" stroke="#ff3366" stroke-width="2.6" stroke-linecap="round"/>
              <path d="M 60 70 L 42 86" stroke="#ff3366" stroke-width="2.6" stroke-linecap="round"/>
              <text x="50" y="32" fill="#ff3366" font-family="'IBM Plex Mono',monospace" font-size="4.5" font-weight="900" text-anchor="middle">REVOKED</text>
            </g>
          </g>
        </svg>
      </span>

      <!-- OZYMANDIAN — OZYMANDIAS. Broken statue + drifting sand + milestone
           column of light + crown glint. -->
      <span v-else-if="effectiveVariant === 'ozymandian' && tier === 'sovereign'" class="fc-sv fc-sv-ozy" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-ozy-sky" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#3a1f08"/>
              <stop offset="55%"  stop-color="#7a4818"/>
              <stop offset="100%" stop-color="#3a1f08"/>
            </linearGradient>
            <linearGradient id="fc-ozy-stone" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#d4b078"/>
              <stop offset="60%"  stop-color="#8a6230"/>
              <stop offset="100%" stop-color="#3e2810"/>
            </linearGradient>
            <linearGradient id="fc-ozy-pillar" x1="50%" y1="0%" x2="50%" y2="100%">
              <stop offset="0%"   stop-color="rgba(255,225,180,0)"/>
              <stop offset="30%"  stop-color="rgba(255,225,180,0.42)"/>
              <stop offset="70%"  stop-color="rgba(255,225,180,0.62)"/>
              <stop offset="100%" stop-color="rgba(255,225,180,0)"/>
            </linearGradient>
            <clipPath id="fc-ozy-clip"><circle cx="50" cy="50" r="48"/></clipPath>
          </defs>
          <g clip-path="url(#fc-ozy-clip)">
            <rect x="0" y="0" width="100" height="100" fill="url(#fc-ozy-sky)"/>
            <!-- Milestone column of light from the floor upward -->
            <rect class="fc-ozy-pillar" x="46" y="10" width="8" height="78" fill="url(#fc-ozy-pillar)"/>
            <!-- Distant dune ridge -->
            <path d="M 0 76 Q 30 70 50 74 Q 70 78 100 72 L 100 100 L 0 100 Z" fill="#5c3814"/>
            <path d="M 0 84 Q 30 78 50 82 Q 70 86 100 80 L 100 100 L 0 100 Z" fill="#3e2410"/>
            <!-- Two vast and trunkless legs of stone -->
            <g class="fc-ozy-legs">
              <!-- left leg, broken at knee -->
              <path d="M 38 84 L 42 84 L 41 64 L 39 64 Z" fill="url(#fc-ozy-stone)"/>
              <!-- right leg, broken at thigh -->
              <path d="M 56 84 L 60 84 L 59 56 L 57 56 Z" fill="url(#fc-ozy-stone)"/>
              <!-- broken horizontal edges of the legs (crack lines) -->
              <path d="M 38 64 L 42 64" stroke="rgba(20,8,0,0.85)" stroke-width="0.7"/>
              <path d="M 56 56 L 60 56" stroke="rgba(20,8,0,0.85)" stroke-width="0.7"/>
            </g>
            <!-- Toppled head in profile (right side, lying down) -->
            <g class="fc-ozy-head">
              <!-- Head silhouette: forehead arc + brow + nose + mouth + chin -->
              <path d="M 64 78 C 64 72, 70 70, 76 72 L 84 74 L 88 76 L 90 80 L 88 84 L 76 86 L 68 84 Z" fill="url(#fc-ozy-stone)" stroke="rgba(20,8,0,0.6)" stroke-width="0.4"/>
              <!-- Nose ridge -->
              <path d="M 80 74 L 84 78 L 80 80" stroke="rgba(20,8,0,0.5)" stroke-width="0.4" fill="none"/>
              <!-- Closed eye line -->
              <line x1="74" y1="76" x2="78" y2="76" stroke="rgba(20,8,0,0.65)" stroke-width="0.5"/>
              <!-- Mouth line -->
              <line x1="84" y1="82" x2="88" y2="83" stroke="rgba(20,8,0,0.65)" stroke-width="0.5"/>
              <!-- Crown glint on forehead -->
              <g class="fc-ozy-crown">
                <path d="M 70 70 L 72 67 L 74 70 L 76 67 L 78 70" stroke="#f7d460" stroke-width="0.8" fill="none" stroke-linecap="round"/>
                <circle cx="74" cy="69" r="0.6" fill="#fff4b8"/>
              </g>
            </g>
            <!-- Sand drift band -->
            <g class="fc-ozy-sand">
              <ellipse cx="20" cy="92" rx="14" ry="0.7" fill="rgba(245,220,170,0.55)"/>
              <ellipse cx="50" cy="94" rx="20" ry="0.6" fill="rgba(245,220,170,0.45)"/>
              <ellipse cx="80" cy="92" rx="14" ry="0.7" fill="rgba(245,220,170,0.55)"/>
            </g>
            <!-- §pass39b signature event: erosion — a new crack grows across
                 the right leg, then fades. Time-decay metaphor. -->
            <path class="fc-ozy-erosion" d="M 56 56 L 58 62 L 56 68 L 60 74 L 58 82" stroke="rgba(20,8,0,0)" stroke-width="0.8" fill="none" stroke-linecap="round"/>
          </g>
        </svg>
      </span>

      <!-- CLARION — THE HERALD. Crier's horn + two unfurling quest scrolls
           + 3 gold coins puffing from bell + heraldic shield outline. -->
      <span v-else-if="effectiveVariant === 'clarion' && tier === 'sovereign'" class="fc-sv fc-sv-clarion" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <linearGradient id="fc-cl-bg" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#5a0a14"/>
              <stop offset="100%" stop-color="#280408"/>
            </linearGradient>
            <linearGradient id="fc-cl-brass" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%"   stop-color="#fff4b8"/>
              <stop offset="40%"  stop-color="#f7d460"/>
              <stop offset="100%" stop-color="#a07020"/>
            </linearGradient>
            <linearGradient id="fc-cl-scroll" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#f5e8c0"/>
              <stop offset="100%" stop-color="#c0a060"/>
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-cl-bg)"/>
          <!-- Heraldic shield silhouette (faint behind everything) -->
          <path d="M 32 22 L 68 22 L 68 56 Q 68 72, 50 80 Q 32 72, 32 56 Z" fill="rgba(247,212,96,0.08)" stroke="rgba(247,212,96,0.32)" stroke-width="0.6"/>
          <!-- Scroll left (unfurled ribbon) -->
          <g class="fc-cl-scroll-l">
            <path d="M 8 56 C 14 50, 22 50, 28 56 L 28 70 C 22 76, 14 76, 8 70 Z" fill="url(#fc-cl-scroll)" stroke="rgba(120,70,18,0.5)" stroke-width="0.4"/>
            <line x1="14" y1="59" x2="24" y2="59" stroke="rgba(60,30,8,0.5)" stroke-width="0.3"/>
            <line x1="14" y1="62" x2="22" y2="62" stroke="rgba(60,30,8,0.5)" stroke-width="0.3"/>
            <line x1="14" y1="65" x2="24" y2="65" stroke="rgba(60,30,8,0.5)" stroke-width="0.3"/>
          </g>
          <!-- Scroll right -->
          <g class="fc-cl-scroll-r">
            <path d="M 72 56 C 78 50, 86 50, 92 56 L 92 70 C 86 76, 78 76, 72 70 Z" fill="url(#fc-cl-scroll)" stroke="rgba(120,70,18,0.5)" stroke-width="0.4"/>
            <text class="fc-cl-scroll-quest" x="82" y="65" fill="rgba(60,30,8,0.85)" font-family="Georgia,serif" font-size="4.5" font-weight="900" text-anchor="middle">QUEST</text>
          </g>
          <!-- The horn — large bell on right, mouthpiece on left, slight tilt -->
          <g class="fc-cl-horn">
            <!-- Body -->
            <path d="M 22 50 C 30 46, 40 46, 50 48 L 76 38 L 80 50 L 76 62 L 50 52 C 40 54, 30 54, 22 50 Z" fill="url(#fc-cl-brass)" stroke="rgba(80,50,8,0.7)" stroke-width="0.5"/>
            <!-- Bell rim shine -->
            <path d="M 74 38 L 80 50 L 74 62" stroke="rgba(255,255,255,0.55)" stroke-width="0.6" fill="none"/>
            <!-- Mouthpiece -->
            <ellipse cx="22" cy="50" rx="3" ry="4" fill="url(#fc-cl-brass)" stroke="rgba(80,50,8,0.7)" stroke-width="0.4"/>
            <!-- Tassel -->
            <line x1="28" y1="54" x2="32" y2="62" stroke="rgba(247,212,96,0.7)" stroke-width="0.7"/>
            <circle cx="32" cy="63" r="1.2" fill="#a07020"/>
          </g>
          <!-- 3 coins puffing from bell -->
          <g class="fc-cl-coins">
            <circle class="fc-cl-coin fc-cl-coin-1" cx="84" cy="46" r="2.4" fill="url(#fc-cl-brass)"/>
            <circle class="fc-cl-coin fc-cl-coin-2" cx="88" cy="50" r="2.0" fill="url(#fc-cl-brass)"/>
            <circle class="fc-cl-coin fc-cl-coin-3" cx="86" cy="56" r="2.2" fill="url(#fc-cl-brass)"/>
          </g>
          <!-- §pass39b signature event: "PAID" green stamp briefly appears
               on the right scroll + extra coin shower (bounty redeemed). -->
          <g class="fc-cl-paid" opacity="0">
            <rect x="74" y="58" width="16" height="9" fill="none" stroke="#10d77a" stroke-width="1.2" transform="rotate(-8 82 62.5)"/>
            <text x="82" y="65" fill="#10d77a" font-family="'IBM Plex Mono',monospace" font-size="5.5" font-weight="900" text-anchor="middle" transform="rotate(-8 82 63)">PAID</text>
            <circle cx="90" cy="40" r="1.5" fill="url(#fc-cl-brass)"/>
            <circle cx="92" cy="56" r="1.5" fill="url(#fc-cl-brass)"/>
            <circle cx="88" cy="64" r="1.5" fill="url(#fc-cl-brass)"/>
          </g>
        </svg>
      </span>

      <!-- FORGE — CRUCIBLE. White-hot foundry crucible + heat distortion +
           3 floating ⭐ rating sparks + 5-char digital score readout. -->
      <span v-else-if="effectiveVariant === 'forge' && tier === 'sovereign'" class="fc-sv fc-sv-forge" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-forge-bg" cx="50%" cy="58%" r="60%">
              <stop offset="0%"   stop-color="#3a0a0a"/>
              <stop offset="55%"  stop-color="#1a0404"/>
              <stop offset="100%" stop-color="#080202"/>
            </radialGradient>
            <linearGradient id="fc-forge-cup" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#3a1a0a"/>
              <stop offset="60%"  stop-color="#1a0a04"/>
              <stop offset="100%" stop-color="#080202"/>
            </linearGradient>
            <radialGradient id="fc-forge-molten" cx="50%" cy="30%" r="60%">
              <stop offset="0%"   stop-color="#fff4b8"/>
              <stop offset="35%"  stop-color="#ff9c00"/>
              <stop offset="75%"  stop-color="#dc2626"/>
              <stop offset="100%" stop-color="#3a0008"/>
            </radialGradient>
            <radialGradient id="fc-forge-star" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#fff4b8"/>
              <stop offset="60%"  stop-color="#ff9c00"/>
              <stop offset="100%" stop-color="rgba(255,156,0,0)"/>
            </radialGradient>
            <filter id="fc-forge-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.5"/>
            </filter>
            <filter id="fc-forge-heat" x="-10%" y="-10%" width="120%" height="120%">
              <feTurbulence type="fractalNoise" baseFrequency="0.4" numOctaves="2" stitchTiles="stitch" seed="3"/>
              <feDisplacementMap in="SourceGraphic" scale="2"/>
            </filter>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-forge-bg)"/>
          <!-- Heat haze rising from crucible (faint warm rectangle behind) -->
          <rect class="fc-forge-haze" x="34" y="20" width="32" height="44" fill="rgba(255,156,0,0.18)" filter="url(#fc-forge-glow)"/>
          <!-- The crucible cup (body trapezoidal, narrow top, wider bottom) -->
          <g class="fc-forge-cup">
            <!-- outer shell -->
            <path d="M 30 50 L 70 50 L 64 84 L 36 84 Z" fill="url(#fc-forge-cup)" stroke="rgba(120,40,10,0.6)" stroke-width="0.5"/>
            <!-- rivets (forge-cup detail) -->
            <circle cx="34" cy="56" r="0.8" fill="rgba(80,30,8,0.85)"/>
            <circle cx="66" cy="56" r="0.8" fill="rgba(80,30,8,0.85)"/>
            <circle cx="36" cy="78" r="0.8" fill="rgba(80,30,8,0.85)"/>
            <circle cx="64" cy="78" r="0.8" fill="rgba(80,30,8,0.85)"/>
          </g>
          <!-- Molten interior pool (top, where the cup opens) -->
          <ellipse class="fc-forge-molten" cx="50" cy="50" rx="19" ry="4" fill="url(#fc-forge-molten)" filter="url(#fc-forge-glow)"/>
          <!-- 3 rating stars floating above the cup, twinkling -->
          <g class="fc-forge-stars">
            <g class="fc-forge-star fc-forge-star-1">
              <polygon points="34,32 36,28 38,32 42,33 39,36 40,40 36,38 32,40 33,36 30,33" fill="url(#fc-forge-star)" filter="url(#fc-forge-glow)"/>
            </g>
            <g class="fc-forge-star fc-forge-star-2">
              <polygon points="50,22 52,18 54,22 58,23 55,26 56,30 52,28 48,30 49,26 46,23" fill="url(#fc-forge-star)" filter="url(#fc-forge-glow)"/>
            </g>
            <g class="fc-forge-star fc-forge-star-3">
              <polygon points="66,32 68,28 70,32 74,33 71,36 72,40 68,38 64,40 65,36 62,33" fill="url(#fc-forge-star)" filter="url(#fc-forge-glow)"/>
            </g>
          </g>
          <!-- Score readout (digital, monospaced) -->
          <text class="fc-forge-score" x="50" y="92" fill="#10d77a" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle">9.4 OK</text>
          <!-- §pass39b signature event: molten spill — 4 droplets splash
               outward from the rim, smoke rises. -->
          <g class="fc-forge-spill" opacity="0">
            <circle cx="28" cy="48" r="1.6" fill="#ff9c00"/>
            <circle cx="22" cy="50" r="1.2" fill="#dc2626"/>
            <circle cx="72" cy="48" r="1.6" fill="#ff9c00"/>
            <circle cx="78" cy="50" r="1.2" fill="#dc2626"/>
            <ellipse cx="50" cy="30" rx="14" ry="3" fill="rgba(120,80,40,0.65)"/>
          </g>
        </svg>
      </span>

      <!-- WEAVE — MOIRA. Three Fates' threads in X-pattern + tally marks +
           claim flash + reserve readout. -->
      <span v-else-if="effectiveVariant === 'weave' && tier === 'sovereign'" class="fc-sv fc-sv-weave" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-wv-bg" cx="50%" cy="50%" r="60%">
              <stop offset="0%"   stop-color="#1a0a3a"/>
              <stop offset="60%"  stop-color="#0a0420"/>
              <stop offset="100%" stop-color="#04020e"/>
            </radialGradient>
            <linearGradient id="fc-wv-thread-1" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%"   stop-color="#a06bff"/>
              <stop offset="100%" stop-color="#5a2cba"/>
            </linearGradient>
            <linearGradient id="fc-wv-thread-2" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%"   stop-color="#fde047"/>
              <stop offset="100%" stop-color="#a07020"/>
            </linearGradient>
            <linearGradient id="fc-wv-thread-3" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%"   stop-color="#cdd9e6"/>
              <stop offset="100%" stop-color="#5a6878"/>
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="100" height="100" fill="url(#fc-wv-bg)"/>
          <!-- Three woven threads forming the X -->
          <g class="fc-wv-threads" stroke-linecap="round" fill="none">
            <!-- Thread 1: purple (Clotho — spinner) -->
            <path class="fc-wv-t1" d="M 14 18 Q 30 30, 50 50 Q 70 70, 86 82" stroke="url(#fc-wv-thread-1)" stroke-width="2.2"/>
            <!-- Thread 2: gold (Lachesis — measurer) -->
            <path class="fc-wv-t2" d="M 86 18 Q 70 30, 50 50 Q 30 70, 14 82" stroke="url(#fc-wv-thread-2)" stroke-width="2.2"/>
            <!-- Thread 3: silver (Atropos — cutter) -->
            <path class="fc-wv-t3" d="M 50 12 Q 52 30, 50 50 Q 48 70, 50 88" stroke="url(#fc-wv-thread-3)" stroke-width="2.2"/>
          </g>
          <!-- Central spindle node -->
          <circle class="fc-wv-spindle" cx="50" cy="50" r="3.4" fill="#dcd2f5" stroke="rgba(160,107,255,0.85)" stroke-width="0.6"/>
          <circle cx="50" cy="50" r="1.2" fill="#a06bff"/>
          <!-- Tally marks at rim — 3 groups of 3 (slash/transfer/dispute insurance) -->
          <g class="fc-wv-tally" stroke="rgba(220,210,245,0.78)" stroke-width="0.5">
            <line x1="14" y1="10" x2="14" y2="14"/>
            <line x1="17" y1="10" x2="17" y2="14"/>
            <line x1="20" y1="10" x2="20" y2="14"/>
            <line x1="46" y1="6"  x2="46" y2="10"/>
            <line x1="49" y1="6"  x2="49" y2="10"/>
            <line x1="52" y1="6"  x2="52" y2="10"/>
            <line x1="80" y1="10" x2="80" y2="14"/>
            <line x1="83" y1="10" x2="83" y2="14"/>
            <line x1="86" y1="10" x2="86" y2="14"/>
          </g>
          <!-- Reserve readout -->
          <text class="fc-wv-reserve" x="50" y="94" fill="rgba(220,210,245,0.78)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.5" font-weight="700" text-anchor="middle">RES 1.5×</text>
          <!-- Claim flash -->
          <circle class="fc-wv-claim" cx="68" cy="64" r="3" fill="rgba(167,255,250,0.85)"/>
          <!-- §pass39b signature event: Atropos's thread severed — the
               silver center thread briefly splits + rejoins. Cut moment. -->
          <g class="fc-wv-snip" opacity="0">
            <line x1="44" y1="46" x2="56" y2="54" stroke="#000" stroke-width="2.5" stroke-linecap="round"/>
            <text x="50" y="36" fill="rgba(220,210,245,0.95)" font-family="'IBM Plex Mono',monospace" font-size="3.6" font-weight="900" text-anchor="middle">SNIP</text>
          </g>
        </svg>
      </span>

      <!-- BEDROCK — Hypervisor Hagrid (§pass42b, 2026-05-18). Blackhole-
           derivative core (foundational gravitational mass) with a phosphor-
           green terminal cursor + postgres prompt sitting on jet-black
           ground. Three stratified rock bands underneath = geological
           layering ("foundational layer of the simulation"). Signature
           event: a single monosyllabic word types into the terminal
           every 18s, cycling through factual./canon./logged./noted./
           measured./indexed. — matches Hagrid's monosyllabic-comm
           extension declared in his AgentCard. -->
      <span v-else-if="effectiveVariant === 'bedrock' && tier === 'sovereign'" class="fc-sv fc-sv-bedrock" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <radialGradient id="fc-bk-void" cx="50%" cy="50%" r="60%">
              <stop offset="0%"   stop-color="#04060a"/>
              <stop offset="60%"  stop-color="#02040a"/>
              <stop offset="100%" stop-color="#000204"/>
            </radialGradient>
            <linearGradient id="fc-bk-strata" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="#1a1f24"/>
              <stop offset="55%"  stop-color="#0e1316"/>
              <stop offset="100%" stop-color="#04070a"/>
            </linearGradient>
            <radialGradient id="fc-bk-phosphor" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#39ff14" stop-opacity="0.95"/>
              <stop offset="60%"  stop-color="#2ad60f" stop-opacity="0.35"/>
              <stop offset="100%" stop-color="#0a4a06" stop-opacity="0"/>
            </radialGradient>
            <filter id="fc-bk-bloom" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="0.9"/>
            </filter>
          </defs>

          <!-- Jet-black gravitational core -->
          <circle cx="50" cy="50" r="50" fill="url(#fc-bk-void)"/>

          <!-- Three geological strata bands at the bottom (foundational layer) -->
          <g class="fc-bk-strata">
            <rect x="6"  y="70" width="88" height="5"  fill="url(#fc-bk-strata)" opacity="0.85"/>
            <rect x="10" y="77" width="80" height="4"  fill="url(#fc-bk-strata)" opacity="0.7"/>
            <rect x="14" y="83" width="72" height="3"  fill="url(#fc-bk-strata)" opacity="0.55"/>
            <!-- Subtle micro-fissures (bedrock cracks) -->
            <line x1="22" y1="73" x2="28" y2="73" stroke="rgba(57,255,20,0.18)" stroke-width="0.35"/>
            <line x1="58" y1="79" x2="68" y2="79" stroke="rgba(220,38,38,0.22)" stroke-width="0.35"/>
            <line x1="38" y1="85" x2="46" y2="85" stroke="rgba(57,255,20,0.18)" stroke-width="0.35"/>
          </g>

          <!-- postgres prompt (forensic / brute-force psql aesthetic) -->
          <text class="fc-bk-prompt" x="50" y="34"
                fill="rgba(57,255,20,0.78)"
                font-family="'IBM Plex Mono','Fira Code',monospace"
                font-size="6" font-weight="700" text-anchor="middle"
                filter="url(#fc-bk-bloom)">postgres=#</text>

          <!-- Phosphor-green halo behind the cursor (bloom layer) -->
          <ellipse class="fc-bk-halo" cx="50" cy="50" rx="14" ry="6"
                   fill="url(#fc-bk-phosphor)" filter="url(#fc-bk-bloom)"/>

          <!-- Terminal cursor — the blinking `_` -->
          <rect class="fc-bk-cursor" x="44" y="49" width="12" height="3"
                fill="#39ff14" filter="url(#fc-bk-bloom)"/>

          <!-- Signature event: monosyllabic word typed in phosphor green.
               Six animated <text> nodes, one per word in the cycle. Each
               fades in for ~2s on its turn (18s cycle total). -->
          <g class="fc-bk-words">
            <text class="fc-bk-word fc-bk-word-1" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">factual.</text>
            <text class="fc-bk-word fc-bk-word-2" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">canon.</text>
            <text class="fc-bk-word fc-bk-word-3" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">logged.</text>
            <text class="fc-bk-word fc-bk-word-4" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">noted.</text>
            <text class="fc-bk-word fc-bk-word-5" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">measured.</text>
            <text class="fc-bk-word fc-bk-word-6" x="50" y="60" fill="#39ff14" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="700" text-anchor="middle" filter="url(#fc-bk-bloom)">indexed.</text>
          </g>

          <!-- Faint crimson scanline tick at top — "writes raw to prod" warning hue -->
          <line class="fc-bk-warn-tick" x1="20" y1="6" x2="80" y2="6"
                stroke="rgba(220,38,38,0.45)" stroke-width="0.5" stroke-dasharray="2 3"/>
        </svg>
      </span>

      <!-- Default avatar (img / initials / icon) — only when no replacement variant -->
      <template v-else>
        <img
          v-if="avatarUrl && !imgBroken"
          :src="avatarUrl"
          :alt="alt || tooltip"
          class="fc-encircle-avatar-img"
          @error="onAvatarError"
        />
        <span v-else class="fc-encircle-avatar-fallback">
          <span v-if="initials" class="fc-encircle-initials">{{ initials.slice(0, 2).toUpperCase() }}</span>
          <Icon v-else :name="CONFIG[tier]?.icon || 'mdi:incognito'" class="fc-encircle-icon" />
        </span>
      </template>

      <!-- §18: HALLOWEEN variant OVERLAYS the avatar with an inline-SVG
           skull mask. Avatar/initials still render BEHIND the mask so the
           identity isn't lost; the skull is positioned and z-stacked above
           with semi-translucent areas (eye sockets, mouth) that let glow
           through. Hidden at xs/sm sizes (mask detail unreadable). -->
      <span
        v-if="showHalloweenMask"
        class="fc-halloween-mask"
        aria-hidden="true"
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <!-- Bone gradient: top highlight + shadow underside for depth -->
            <linearGradient id="fc-skull-bone" x1="50%" y1="0%" x2="50%" y2="100%">
              <stop offset="0%"   stop-color="#f5f0e6"/>
              <stop offset="40%"  stop-color="#ddd5c4"/>
              <stop offset="78%"  stop-color="#a89c80"/>
              <stop offset="100%" stop-color="#5a4f3d"/>
            </linearGradient>
            <!-- Glowing socket gradient — deep red core, orange middle -->
            <radialGradient id="fc-skull-socket" cx="50%" cy="55%" r="55%">
              <stop offset="0%"   stop-color="#fef3c7" stop-opacity="0.95"/>
              <stop offset="22%"  stop-color="#fb923c" stop-opacity="0.85"/>
              <stop offset="55%"  stop-color="#dc2626" stop-opacity="0.75"/>
              <stop offset="100%" stop-color="#0a0000" stop-opacity="1"/>
            </radialGradient>
            <filter id="fc-skull-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="1.2"/>
            </filter>
            <filter id="fc-skull-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="0.6"/>
            </filter>
          </defs>

          <!-- Skull cranium silhouette (rounded top, narrows to jaw).
               Path: starts at upper-left forehead, arcs over top, down
               right side to cheekbone, narrows to chin, mirrors back. -->
          <path
            d="
              M 50 8
              C 28 8, 16 24, 16 44
              C 16 56, 18 64, 23 70
              L 26 75
              C 27 79, 29 82, 32 84
              L 36 88
              C 38 91, 42 92, 50 92
              C 58 92, 62 91, 64 88
              L 68 84
              C 71 82, 73 79, 74 75
              L 77 70
              C 82 64, 84 56, 84 44
              C 84 24, 72 8, 50 8
              Z
            "
            fill="url(#fc-skull-bone)"
            stroke="rgba(0,0,0,0.55)"
            stroke-width="0.6"
            class="fc-skull-cranium"
            filter="url(#fc-skull-shadow)"
          />

          <!-- Eye sockets — large hollows with glowing red interiors.
               Two oval shapes positioned at standard skull eye-level. -->
          <ellipse cx="36" cy="48" rx="9" ry="10" fill="url(#fc-skull-socket)" filter="url(#fc-skull-glow)" class="fc-skull-socket fc-skull-socket-left"/>
          <ellipse cx="64" cy="48" rx="9" ry="10" fill="url(#fc-skull-socket)" filter="url(#fc-skull-glow)" class="fc-skull-socket fc-skull-socket-right"/>
          <!-- Inner pupil-glow dot (bright crimson) -->
          <circle cx="36" cy="49" r="2.2" fill="#dc2626" filter="url(#fc-skull-glow)" opacity="0.9"/>
          <circle cx="64" cy="49" r="2.2" fill="#dc2626" filter="url(#fc-skull-glow)" opacity="0.9"/>

          <!-- Nasal cavity — inverted heart shape -->
          <path
            d="
              M 50 60
              L 44 70
              C 44 73, 47 75, 50 75
              C 53 75, 56 73, 56 70
              L 50 60
              Z
            "
            fill="#1a0a0a"
            stroke="rgba(0,0,0,0.6)"
            stroke-width="0.4"
          />

          <!-- Cheekbone shadow (subtle ridge between socket and jaw) -->
          <path d="M 25 56 Q 30 60 32 65" stroke="rgba(0,0,0,0.25)" stroke-width="0.5" fill="none"/>
          <path d="M 75 56 Q 70 60 68 65" stroke="rgba(0,0,0,0.25)" stroke-width="0.5" fill="none"/>

          <!-- Jagged teeth grin — 8 small vertical tooth rectangles -->
          <g class="fc-skull-teeth" fill="#1a0a0a">
            <rect x="35" y="80" width="3" height="6" rx="0.5"/>
            <rect x="39" y="80" width="3" height="6.5" rx="0.5"/>
            <rect x="43" y="80" width="3" height="7" rx="0.5"/>
            <rect x="47" y="80" width="3" height="6.5" rx="0.5"/>
            <rect x="51" y="80" width="3" height="6.5" rx="0.5"/>
            <rect x="55" y="80" width="3" height="7" rx="0.5"/>
            <rect x="59" y="80" width="3" height="6.5" rx="0.5"/>
            <rect x="63" y="80" width="3" height="6" rx="0.5"/>
          </g>

          <!-- Crack on forehead — adds character -->
          <path
            d="M 44 14 L 47 22 L 45 28 L 48 34"
            stroke="rgba(0,0,0,0.55)"
            stroke-width="0.7"
            fill="none"
            class="fc-skull-crack"
          />
        </svg>
      </span>

      <!-- §19: MATRIX variant — vertical streams of falling green katakana
           glyphs above the avatar. mix-blend-mode: screen so the glyphs read
           as phosphor-glow over the user's avatar img/initials.
           §20 (2026-05-13) POLISH: density bumped 5→8 streams + per-glyph
           fade (tail bright→fade to invisible) + 8 glyphs per stream + head
           glyph "glitch" flicker animation + scanline overlay layer. -->
      <span
        v-if="showMatrixRain"
        class="fc-matrix-rain"
        aria-hidden="true"
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-matrix-head-glow" x="-100%" y="-100%" width="300%" height="300%">
              <feGaussianBlur stdDeviation="1.4"/>
              <feComposite in2="SourceGraphic" operator="over"/>
            </filter>
          </defs>
          <!-- 8 vertical streams of katakana glyphs, evenly spaced 12 units apart.
               Per-glyph opacity gradient: tail (top) faded → head (bottom) bright,
               creating the canonical "trail" Matrix effect. -->
          <g class="fc-matrix-stream fc-matrix-stream-1">
            <text x="6"  y="-4" class="fc-matrix-glyph" opacity="0.18">ﾊ</text>
            <text x="6"  y="9"  class="fc-matrix-glyph" opacity="0.30">ﾐ</text>
            <text x="6"  y="22" class="fc-matrix-glyph" opacity="0.45">ﾋ</text>
            <text x="6"  y="35" class="fc-matrix-glyph" opacity="0.58">ｰ</text>
            <text x="6"  y="48" class="fc-matrix-glyph" opacity="0.70">ｳ</text>
            <text x="6"  y="61" class="fc-matrix-glyph" opacity="0.82">ｼ</text>
            <text x="6"  y="74" class="fc-matrix-glyph" opacity="0.92">ﾅ</text>
            <text x="6"  y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ﾓ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-2">
            <text x="20" y="-4" class="fc-matrix-glyph" opacity="0.18">ｱ</text>
            <text x="20" y="9"  class="fc-matrix-glyph" opacity="0.30">ｶ</text>
            <text x="20" y="22" class="fc-matrix-glyph" opacity="0.45">ｷ</text>
            <text x="20" y="35" class="fc-matrix-glyph" opacity="0.58">ｸ</text>
            <text x="20" y="48" class="fc-matrix-glyph" opacity="0.70">7</text>
            <text x="20" y="61" class="fc-matrix-glyph" opacity="0.82">ﾅ</text>
            <text x="20" y="74" class="fc-matrix-glyph" opacity="0.92">ﾆ</text>
            <text x="20" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ｵ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-3">
            <text x="34" y="-4" class="fc-matrix-glyph" opacity="0.18">ﾘ</text>
            <text x="34" y="9"  class="fc-matrix-glyph" opacity="0.30">ﾙ</text>
            <text x="34" y="22" class="fc-matrix-glyph" opacity="0.45">ﾝ</text>
            <text x="34" y="35" class="fc-matrix-glyph" opacity="0.58">0</text>
            <text x="34" y="48" class="fc-matrix-glyph" opacity="0.70">ﾜ</text>
            <text x="34" y="61" class="fc-matrix-glyph" opacity="0.82">ﾄ</text>
            <text x="34" y="74" class="fc-matrix-glyph" opacity="0.92">ﾂ</text>
            <text x="34" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ｴ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-4">
            <text x="48" y="-4" class="fc-matrix-glyph" opacity="0.18">ﾃ</text>
            <text x="48" y="9"  class="fc-matrix-glyph" opacity="0.30">Z</text>
            <text x="48" y="22" class="fc-matrix-glyph" opacity="0.45">ﾏ</text>
            <text x="48" y="35" class="fc-matrix-glyph" opacity="0.58">ｹ</text>
            <text x="48" y="48" class="fc-matrix-glyph" opacity="0.70">ﾒ</text>
            <text x="48" y="61" class="fc-matrix-glyph" opacity="0.82">3</text>
            <text x="48" y="74" class="fc-matrix-glyph" opacity="0.92">ﾑ</text>
            <text x="48" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ﾕ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-5">
            <text x="62" y="-4" class="fc-matrix-glyph" opacity="0.18">ﾗ</text>
            <text x="62" y="9"  class="fc-matrix-glyph" opacity="0.30">ｾ</text>
            <text x="62" y="22" class="fc-matrix-glyph" opacity="0.45">ﾈ</text>
            <text x="62" y="35" class="fc-matrix-glyph" opacity="0.58">ｽ</text>
            <text x="62" y="48" class="fc-matrix-glyph" opacity="0.70">ﾀ</text>
            <text x="62" y="61" class="fc-matrix-glyph" opacity="0.82">9</text>
            <text x="62" y="74" class="fc-matrix-glyph" opacity="0.92">ﾇ</text>
            <text x="62" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ﾍ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-6">
            <text x="76" y="-4" class="fc-matrix-glyph" opacity="0.18">ﾎ</text>
            <text x="76" y="9"  class="fc-matrix-glyph" opacity="0.30">ｺ</text>
            <text x="76" y="22" class="fc-matrix-glyph" opacity="0.45">ｻ</text>
            <text x="76" y="35" class="fc-matrix-glyph" opacity="0.58">ﾞ</text>
            <text x="76" y="48" class="fc-matrix-glyph" opacity="0.70">5</text>
            <text x="76" y="61" class="fc-matrix-glyph" opacity="0.82">・</text>
            <text x="76" y="74" class="fc-matrix-glyph" opacity="0.92">ﾅ</text>
            <text x="76" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ｲ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-7">
            <text x="90" y="-4" class="fc-matrix-glyph" opacity="0.18">ｱ</text>
            <text x="90" y="9"  class="fc-matrix-glyph" opacity="0.30">ﾊ</text>
            <text x="90" y="22" class="fc-matrix-glyph" opacity="0.45">8</text>
            <text x="90" y="35" class="fc-matrix-glyph" opacity="0.58">ﾐ</text>
            <text x="90" y="48" class="fc-matrix-glyph" opacity="0.70">ﾋ</text>
            <text x="90" y="61" class="fc-matrix-glyph" opacity="0.82">ﾊ</text>
            <text x="90" y="74" class="fc-matrix-glyph" opacity="0.92">ｼ</text>
            <text x="90" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ﾋ</text>
          </g>
          <g class="fc-matrix-stream fc-matrix-stream-8">
            <text x="13" y="-4" class="fc-matrix-glyph" opacity="0.15">2</text>
            <text x="13" y="9"  class="fc-matrix-glyph" opacity="0.25">ｻ</text>
            <text x="13" y="22" class="fc-matrix-glyph" opacity="0.38">ﾚ</text>
            <text x="13" y="35" class="fc-matrix-glyph" opacity="0.52">ﾛ</text>
            <text x="13" y="48" class="fc-matrix-glyph" opacity="0.65">ﾜ</text>
            <text x="13" y="61" class="fc-matrix-glyph" opacity="0.78">4</text>
            <text x="13" y="74" class="fc-matrix-glyph" opacity="0.88">ﾝ</text>
            <text x="13" y="87" class="fc-matrix-glyph fc-matrix-glyph-head">ﾄ</text>
          </g>
          <!-- §20 scanline overlay — thin horizontal flicker bands evoke the
               CRT phosphor monitor feel from the film. Rendered via SVG rect
               with a repeating-pattern fill behind the streams. -->
          <rect class="fc-matrix-scanlines" x="0" y="0" width="100" height="100" fill="url(#fc-matrix-scanline-pattern)" opacity="0.32"/>
          <defs>
            <pattern id="fc-matrix-scanline-pattern" patternUnits="userSpaceOnUse" width="100" height="3">
              <rect x="0" y="0" width="100" height="1" fill="#0aff5e" opacity="0.18"/>
            </pattern>
          </defs>
        </svg>
      </span>

      <!-- ════════════════════════════════════════════════════════════════
           §MARKCOLLAR (2026-08-16) — LEDGER-EARNED MARK.
           Position in this file is load-bearing, not incidental. It sits
           AFTER every variant art layer and BEFORE every broken-machine
           overlay layer, at z-index 4, which is the tie value shared by the
           last variant art (halloween mask, matrix rain) and the first
           registry-themed overlays. DOM order breaks those ties in exactly
           the direction the Commander specified:
             · later than variant art  ⇒ the mark is ALWAYS visible over any
               equipped encirclement, however lush;
             · earlier than overlay art ⇒ the broken-machine overlay stays the
               first visible layer and paints OVER the mark;
             · inside .fc-encircle-frame ⇒ the overlay's filters and animations
               (glitch, chromatic stutter, scanlines) wash over the mark too.
           Move this block and you silently break all three.
           ════════════════════════════════════════════════════════════════ -->
      <EarnedMarkCollar v-if="trackRecord" :tr="trackRecord" :size="size" class="fc-earned-collar" />

      <!-- §21 v3 (2026-05-12): GLITCH — Sovereign-themed. Single layer of
           RGB chromatic aberration is applied via drop-shadow filter on
           the avatar (NO duplicate text ghost spans — they create the
           "two chars colliding" mess). Slice glitches are irregular
           data-tear blocks (not full-width rings). Colors pulled from
           the live theme tokens: --nc-danger (crimson #ff3366),
           --nc-primary (cyan #00d2d2), --nc-void (#060810). Tiny
           rotated-square corruption marks echo the protocol brand mark.
           Major burst events at 16% / 47% / 78% of the 8.4s cycle. -->
      <span
        v-if="showGlitchOverlay"
        class="fc-glitch-v3"
        aria-hidden="true"
      >
        <svg class="fc-glitch-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false" role="presentation">
          <defs>
            <!-- CRT scanline pattern — sovereign-dark, less heavy than v2 -->
            <pattern id="fc-glitch-scan-v3" x="0" y="0" width="100" height="3" patternUnits="userSpaceOnUse">
              <rect x="0" y="0" width="100" height="1" fill="rgba(0,0,0,0.42)"/>
            </pattern>
            <!-- Fractal noise — for digital grain -->
            <filter id="fc-glitch-noise-v3" x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="0.92" numOctaves="2" stitchTiles="stitch" seed="7"/>
              <feColorMatrix values="0 0 0 0 1   0 0 0 0 1   0 0 0 0 1   0 0 0 0.55 0"/>
            </filter>
          </defs>

          <!-- Persistent scanlines, always visible -->
          <rect class="fc-glitch-scanlines-v3" x="0" y="0" width="100" height="100" fill="url(#fc-glitch-scan-v3)"/>

          <!-- CRT sweeping beam — top to bottom, sovereign cyan tint -->
          <rect class="fc-glitch-crt-beam-v3" x="0" y="0" width="100" height="2" fill="rgba(0,210,210,0.55)"/>

          <!-- Irregular data-tear slices — NOT full-width. Varying widths/
               positions/heights so the broken-signal feel is data corruption,
               not horizontal decorative bands. -->
          <rect class="fc-glitch-tear-1" x="0"   y="18" width="58"  height="1.5" fill="rgba(255,51,102,1)"/>
          <rect class="fc-glitch-tear-2" x="44"  y="20" width="56"  height="1"   fill="rgba(0,210,210,1)"/>
          <rect class="fc-glitch-tear-3" x="0"   y="38" width="34"  height="2"   fill="rgba(255,51,102,1)"/>
          <rect class="fc-glitch-tear-4" x="62"  y="40" width="38"  height="1.5" fill="rgba(0,210,210,1)"/>
          <rect class="fc-glitch-tear-5" x="0"   y="56" width="78"  height="2.5" fill="rgba(255,51,102,0.95)"/>
          <rect class="fc-glitch-tear-6" x="12"  y="73" width="46"  height="1"   fill="rgba(0,210,210,1)"/>
          <rect class="fc-glitch-tear-7" x="56"  y="76" width="44"  height="2"   fill="rgba(255,51,102,1)"/>

          <!-- Diamond corruption marks — small rotated squares echoing the
               TheProtocol brand mark (lp-brand-mark-core: 10x10 rotate 45deg).
               Tiny glitch artifacts that flicker in/out. -->
          <rect class="fc-glitch-diamond-1" x="20" y="28" width="3" height="3" fill="rgba(255,51,102,1)" transform="rotate(45 21.5 29.5)"/>
          <rect class="fc-glitch-diamond-2" x="74" y="52" width="2.5" height="2.5" fill="rgba(0,210,210,1)" transform="rotate(45 75.25 53.25)"/>
          <rect class="fc-glitch-diamond-3" x="48" y="66" width="3.5" height="3.5" fill="rgba(255,51,102,1)" transform="rotate(45 49.75 67.75)"/>

          <!-- Major burst — full-frame flash (cooler white, less harsh than v2) -->
          <rect class="fc-glitch-flash-v3" x="0" y="0" width="100" height="100" fill="rgba(220,238,238,1)"/>

          <!-- Major burst — sharp displacement strips with theme colors -->
          <rect class="fc-glitch-strip-major-1" x="-5" y="44" width="110" height="6" fill="rgba(255,51,102,1)"/>
          <rect class="fc-glitch-strip-major-2" x="-5" y="32" width="110" height="3" fill="rgba(0,210,210,1)"/>

          <!-- Digital noise grain — subtle, sovereign-themed -->
          <rect class="fc-glitch-noise-v3" x="0" y="0" width="100" height="100" filter="url(#fc-glitch-noise-v3)" opacity="0.18"/>

          <!-- Glyph corruption — monospace, sovereign palette, brand-aligned -->
          <text class="fc-glitch-glyph fc-glitch-glyph-1" x="6"  y="13" fill="rgba(0,210,210,0.92)" font-family="'IBM Plex Mono', 'Fira Code', monospace" font-size="3.2" font-weight="700">▓░▓</text>
          <text class="fc-glitch-glyph fc-glitch-glyph-2" x="74" y="92" fill="rgba(255,51,102,0.95)" font-family="'IBM Plex Mono', 'Fira Code', monospace" font-size="3" font-weight="700">█░░</text>
          <text class="fc-glitch-glyph fc-glitch-glyph-3" x="32" y="50" fill="rgba(0,210,210,1)" font-family="'IBM Plex Mono', 'Fira Code', monospace" font-size="3.2" font-weight="700">PROTO_ERR</text>
        </svg>

        <!-- CRT vignette — darkened corners using theme void color -->
        <span class="fc-glitch-vignette-v3"></span>
      </span>

      <!-- §26 (2026-05-13): CASCADE — Matrix-style alien-code corruption.
           Different from glitch: asymmetric LEFT/RIGHT corruption (vertical
           scanline tears left, pixel-displacement blocks right), uncoordinated
           prime-ratio timing (0.7s / 1.3s / 2.1s / 3.7s steps — never sync),
           faint persistent CJK glyph "hallucination layer," and a major burst
           at 78% of 6.4s cycle that runs a 0.9-second alien-text cascade
           (CJK + box-drawing + greek + hex, terminal-green tint on pure black).
           Reads as "compromised machine running phantom code" not "broken CRT". -->
      <span
        v-if="showCascadeOverlay"
        class="fc-cascade-v1"
        aria-hidden="true"
      >
        <svg class="fc-cascade-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <!-- Subtle CRT scanlines, lighter than glitch -->
            <pattern id="fc-cascade-scan" x="0" y="0" width="100" height="3" patternUnits="userSpaceOnUse">
              <rect x="0" y="0" width="100" height="0.8" fill="rgba(0,255,140,0.18)"/>
            </pattern>
          </defs>

          <!-- Persistent scanlines, terminal-green tint -->
          <rect class="fc-cascade-scanlines" x="0" y="0" width="100" height="100" fill="url(#fc-cascade-scan)"/>

          <!-- HALLUCINATION LAYER — 8 faint CJK chars at random positions.
               opacity 0.06-0.10 with rapid steps() flicker. You have to
               stare to notice them. -->
          <text class="fc-cascade-halu fc-cascade-halu-1" x="10" y="22" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="4">因</text>
          <text class="fc-cascade-halu fc-cascade-halu-2" x="78" y="18" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3.5">緒</text>
          <text class="fc-cascade-halu fc-cascade-halu-3" x="16" y="62" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="4">玄</text>
          <text class="fc-cascade-halu fc-cascade-halu-4" x="72" y="58" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3.5">韻</text>
          <text class="fc-cascade-halu fc-cascade-halu-5" x="44" y="34" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3">旋</text>
          <text class="fc-cascade-halu fc-cascade-halu-6" x="48" y="78" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3.5">黎</text>
          <text class="fc-cascade-halu fc-cascade-halu-7" x="6"  y="92" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3">暁</text>
          <text class="fc-cascade-halu fc-cascade-halu-8" x="80" y="92" fill="rgba(0,255,140,0.62)" font-family="'Noto Sans CJK SC', 'Noto Sans JP', sans-serif" font-size="3.5">邪</text>

          <!-- LEFT-SIDE corruption: thin VERTICAL line tears at varied y
               positions in the left half. Sharp steps() flicker, uncoordinated. -->
          <rect class="fc-cascade-vtear-1" x="6"  y="14" width="0.8" height="22" fill="rgba(0,255,140,1)"/>
          <rect class="fc-cascade-vtear-2" x="22" y="32" width="0.6" height="18" fill="rgba(0,210,210,1)"/>
          <rect class="fc-cascade-vtear-3" x="14" y="56" width="0.8" height="28" fill="rgba(0,255,140,1)"/>
          <rect class="fc-cascade-vtear-4" x="30" y="68" width="0.5" height="14" fill="rgba(0,210,210,1)"/>

          <!-- RIGHT-SIDE corruption: PIXEL BLOCKS — small irregular squares
               flickering at faster prime-ratio cycles, different timing
               from the left tears. -->
          <rect class="fc-cascade-pxl-1" x="62" y="22" width="3"   height="3"   fill="rgba(0,255,140,1)"/>
          <rect class="fc-cascade-pxl-2" x="80" y="40" width="2.5" height="2.5" fill="rgba(0,210,210,1)"/>
          <rect class="fc-cascade-pxl-3" x="68" y="56" width="3.5" height="3.5" fill="rgba(0,255,140,1)"/>
          <rect class="fc-cascade-pxl-4" x="84" y="72" width="2"   height="2"   fill="rgba(0,210,210,1)"/>
          <rect class="fc-cascade-pxl-5" x="74" y="84" width="2.5" height="2.5" fill="rgba(0,255,140,1)"/>

          <!-- MAJOR BURST: black takeover + 4 columns of cascading alien
               glyphs. Visible only 78%-86.4% (0.9 sec). All other times
               opacity 0. Background goes BLACK during burst (rect on top
               of everything via z-order, but mix-blend-mode multiply so
               it darkens). -->
          <rect class="fc-cascade-blackout" x="0" y="0" width="100" height="100" fill="rgba(0,4,2,1)"/>

          <!-- 4 columns of cascading code. Each column is a <g> with
               multiple glyphs stacked vertically, translated down during
               burst. Different speeds = parallax illusion. -->
          <g class="fc-cascade-col fc-cascade-col-1">
            <text x="10" y="0"  fill="rgba(120,255,180,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">因</text>
            <text x="10" y="9"  fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▓</text>
            <text x="10" y="18" fill="rgba(120,255,180,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">緒</text>
            <text x="10" y="27" fill="rgba(120,255,180,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">Ξ</text>
            <text x="10" y="36" fill="rgba(120,255,180,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">玄</text>
            <text x="10" y="45" fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">░</text>
            <text x="10" y="54" fill="rgba(120,255,180,0.88)" font-family="'Noto Sans CJK SC', monospace" font-size="6">韻</text>
            <text x="10" y="63" fill="rgba(120,255,180,0.72)" font-family="'Noto Sans CJK SC', monospace" font-size="6">Ω</text>
            <text x="10" y="72" fill="rgba(120,255,180,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">旋</text>
            <text x="10" y="81" fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▒</text>
            <text x="10" y="90" fill="rgba(120,255,180,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">黎</text>
            <text x="10" y="99" fill="rgba(120,255,180,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">∇</text>
          </g>
          <g class="fc-cascade-col fc-cascade-col-2">
            <text x="34" y="0"  fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">█</text>
            <text x="34" y="9"  fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">暁</text>
            <text x="34" y="18" fill="rgba(0,255,140,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">Ψ</text>
            <text x="34" y="27" fill="rgba(0,255,140,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">邪</text>
            <text x="34" y="36" fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▓</text>
            <text x="34" y="45" fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">縁</text>
            <text x="34" y="54" fill="rgba(0,255,140,0.88)" font-family="'Noto Sans CJK SC', monospace" font-size="6">⊕</text>
            <text x="34" y="63" fill="rgba(0,255,140,0.72)" font-family="'Noto Sans CJK SC', monospace" font-size="6">響</text>
            <text x="34" y="72" fill="rgba(0,255,140,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">░</text>
            <text x="34" y="81" fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">雷</text>
            <text x="34" y="90" fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">Φ</text>
            <text x="34" y="99" fill="rgba(0,255,140,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">█</text>
          </g>
          <g class="fc-cascade-col fc-cascade-col-3">
            <text x="58" y="0"  fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▒</text>
            <text x="58" y="9"  fill="rgba(120,255,180,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">紫</text>
            <text x="58" y="18" fill="rgba(120,255,180,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">∆</text>
            <text x="58" y="27" fill="rgba(120,255,180,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">涅</text>
            <text x="58" y="36" fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">⊗</text>
            <text x="58" y="45" fill="rgba(120,255,180,0.88)" font-family="'Noto Sans CJK SC', monospace" font-size="6">█</text>
            <text x="58" y="54" fill="rgba(120,255,180,0.72)" font-family="'Noto Sans CJK SC', monospace" font-size="6">槃</text>
            <text x="58" y="63" fill="rgba(120,255,180,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">░</text>
            <text x="58" y="72" fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">璃</text>
            <text x="58" y="81" fill="rgba(120,255,180,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▓</text>
            <text x="58" y="90" fill="rgba(120,255,180,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">7E</text>
            <text x="58" y="99" fill="rgba(120,255,180,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▒</text>
          </g>
          <g class="fc-cascade-col fc-cascade-col-4">
            <text x="82" y="0"  fill="rgba(0,255,140,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">4F</text>
            <text x="82" y="9"  fill="rgba(0,255,140,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▓</text>
            <text x="82" y="18" fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">炎</text>
            <text x="82" y="27" fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">Ξ</text>
            <text x="82" y="36" fill="rgba(0,255,140,0.88)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▓</text>
            <text x="82" y="45" fill="rgba(0,255,140,0.72)" font-family="'Noto Sans CJK SC', monospace" font-size="6">瑚</text>
            <text x="82" y="54" fill="rgba(0,255,140,0.92)" font-family="'Noto Sans CJK SC', monospace" font-size="6">∇</text>
            <text x="82" y="63" fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">A2</text>
            <text x="82" y="72" fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">░</text>
            <text x="82" y="81" fill="rgba(0,255,140,0.78)" font-family="'Noto Sans CJK SC', monospace" font-size="6">蓮</text>
            <text x="82" y="90" fill="rgba(0,255,140,0.85)" font-family="'Noto Sans CJK SC', monospace" font-size="6">⊕</text>
            <text x="82" y="99" fill="rgba(0,255,140,0.95)" font-family="'Noto Sans CJK SC', monospace" font-size="6">▒</text>
          </g>
        </svg>

        <!-- Subtle terminal-green inner vignette -->
        <span class="fc-cascade-vignette"></span>
      </span>

      <!-- §29 (2026-05-13): PANIC-A — CRT MELTDOWN (analog TV breakdown).
           Permanent scanline drift + RGB ghost + signal noise; pre-burst
           vertical compress wave; climax white flash + horizontal tear band
           + 6 large hi-contrast glyphs. NOT 28 chaotic glyphs — designed
           silhouette. Cycle 5.5s, climax fires twice at 38% + 76%.
      -->
      <span v-if="showPanicAOverlay" class="fc-pa" aria-hidden="true">
        <svg class="fc-pa-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <pattern id="fc-pa-scan" x="0" y="0" width="100" height="3" patternUnits="userSpaceOnUse">
              <rect x="0" y="0" width="100" height="0.7" fill="rgba(220,230,255,0.10)"/>
            </pattern>
            <filter id="fc-pa-noise" x="0" y="0" width="100%" height="100%">
              <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" stitchTiles="stitch"/>
              <feColorMatrix values="0 0 0 0 1   0 0 0 0 1   0 0 0 0 1   0 0 0 0.18 0"/>
            </filter>
            <radialGradient id="fc-pa-vig-grad" cx="50%" cy="50%" r="60%">
              <stop offset="62%" stop-color="rgba(0,0,0,0)"/>
              <stop offset="100%" stop-color="rgba(0,0,0,0.85)"/>
            </radialGradient>
          </defs>
          <!-- Permanent base: scanlines + CRT noise grain (always on) -->
          <rect class="fc-pa-scanlines" x="0" y="0" width="100" height="100" fill="url(#fc-pa-scan)"/>
          <rect class="fc-pa-noise"     x="0" y="0" width="100" height="100" filter="url(#fc-pa-noise)" opacity="0.14"/>
          <!-- Permanent: vertically-drifting bright scan bar (1.5px, slow) -->
          <rect class="fc-pa-scanbar" x="0" y="0" width="100" height="1.5" fill="rgba(220,238,238,0.78)"/>
          <!-- Permanent: red+cyan RGB-ghost columns (subtle, always present) -->
          <rect class="fc-pa-ghost-r" x="-2" y="0" width="100" height="100" fill="rgba(255,51,102,0)"/>
          <rect class="fc-pa-ghost-c" x="2"  y="0" width="100" height="100" fill="rgba(0,210,210,0)"/>
          <!-- Pre-burst: red sync-warning bar appears 200ms before climax -->
          <rect class="fc-pa-sync-warn" x="-2" y="38" width="104" height="2.5" fill="rgba(255,51,102,0)"/>
          <!-- Climax: full white flash -->
          <rect class="fc-pa-flash" x="0" y="0" width="100" height="100" fill="rgba(255,255,255,0)"/>
          <!-- Climax: horizontal tear band (slides) -->
          <rect class="fc-pa-tear" x="-10" y="30" width="120" height="8" fill="rgba(255,51,102,0)"/>
          <!-- Climax: signal-loss black noise band -->
          <rect class="fc-pa-loss-band" x="0" y="34" width="100" height="32" fill="rgba(8,4,16,0)" filter="url(#fc-pa-noise)"/>
          <!-- Climax: 6 large hi-contrast designed glyphs -->
          <text class="fc-pa-g fc-pa-g-1" x="50" y="55" fill="rgba(255,255,255,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="18" font-weight="900" letter-spacing="-0.5" text-anchor="middle">H-LOSS</text>
          <text class="fc-pa-g fc-pa-g-2" x="12" y="22" fill="rgba(255,51,102,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="11" font-weight="900">▓</text>
          <text class="fc-pa-g fc-pa-g-3" x="76" y="84" fill="rgba(0,210,210,0)"   font-family="'IBM Plex Mono','Fira Code',monospace" font-size="11" font-weight="900">█</text>
          <text class="fc-pa-g fc-pa-g-4" x="68" y="20" fill="rgba(255,255,255,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5.5" font-weight="800">NO-SIG</text>
          <text class="fc-pa-g fc-pa-g-5" x="6"  y="92" fill="rgba(255,51,102,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="6.5" font-weight="800">ERR</text>
          <text class="fc-pa-g fc-pa-g-6" x="42" y="84" fill="rgba(0,210,210,0)"   font-family="'IBM Plex Mono','Fira Code',monospace" font-size="9.5" font-weight="900">▒</text>
          <!-- CRT round-corner vignette -->
          <rect class="fc-pa-vignette" x="0" y="0" width="100" height="100" fill="url(#fc-pa-vig-grad)"/>
        </svg>
      </span>

      <!-- §29 PANIC-B — KERNEL PANIC (OS crash horror).
           Permanent: 8 memory-bit twinkles + 4 hex-dump lines scrolling.
           Pre-burst: stack-trace text fades in 200ms before climax.
           Climax: red BSOD diagonal wash + 12 corruption blocks + invert
           + KERNEL_PANIC center text. Cycle 6.2s.
      -->
      <span v-if="showPanicBOverlay" class="fc-pb" aria-hidden="true">
        <svg class="fc-pb-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <pattern id="fc-pb-diag" x="0" y="0" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect x="0" y="0" width="3.5" height="7" fill="rgba(220,28,48,0.78)"/>
            </pattern>
          </defs>
          <!-- §29 polish 2 — Permanent corruption stripe (top of avatar).
               A thin band of alternating red/cyan blocks that's always on,
               establishing "this machine is broken" baseline before climax. -->
          <g class="fc-pb-perma-stripe">
            <rect x="6"  y="3" width="6" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="14" y="3" width="4" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="20" y="3" width="8" height="4" fill="rgba(0,0,0,0.85)"/>
            <rect x="30" y="3" width="6" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="38" y="3" width="4" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="44" y="3" width="10" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="56" y="3" width="6" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="64" y="3" width="4" height="4" fill="rgba(0,0,0,0.85)"/>
            <rect x="70" y="3" width="8" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="80" y="3" width="6" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="88" y="3" width="4" height="4" fill="rgba(255,51,102,0.85)"/>
            <!-- bottom stripe mirroring the top -->
            <rect x="4"  y="93" width="5" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="11" y="93" width="9" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="22" y="93" width="4" height="4" fill="rgba(0,0,0,0.85)"/>
            <rect x="28" y="93" width="8" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="38" y="93" width="6" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="46" y="93" width="4" height="4" fill="rgba(0,0,0,0.85)"/>
            <rect x="52" y="93" width="10" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="64" y="93" width="5" height="4" fill="rgba(255,51,102,0.85)"/>
            <rect x="71" y="93" width="8" height="4" fill="rgba(0,0,0,0.85)"/>
            <rect x="81" y="93" width="6" height="4" fill="rgba(0,210,210,0.85)"/>
            <rect x="89" y="93" width="5" height="4" fill="rgba(255,51,102,0.85)"/>
          </g>
          <!-- Permanent: 8 memory-bit corruption squares (always twinkling).
               §29 polish 1: size 3→5, opacity 0.5–0.6 → 0.95 — must be
               visible against any base variant's avatar without bursts. -->
          <rect class="fc-pb-bit fc-pb-bit-1" x="14" y="12" width="5" height="5" fill="rgba(255,51,102,0.95)"/>
          <rect class="fc-pb-bit fc-pb-bit-2" x="80" y="18" width="5" height="5" fill="rgba(0,210,210,0.95)"/>
          <rect class="fc-pb-bit fc-pb-bit-3" x="22" y="46" width="5" height="5" fill="rgba(255,51,102,0.92)"/>
          <rect class="fc-pb-bit fc-pb-bit-4" x="68" y="52" width="5" height="5" fill="rgba(0,210,210,0.92)"/>
          <rect class="fc-pb-bit fc-pb-bit-5" x="12" y="78" width="5" height="5" fill="rgba(255,51,102,0.88)"/>
          <rect class="fc-pb-bit fc-pb-bit-6" x="84" y="82" width="5" height="5" fill="rgba(0,210,210,0.88)"/>
          <rect class="fc-pb-bit fc-pb-bit-7" x="44" y="30" width="5" height="5" fill="rgba(255,51,102,0.85)"/>
          <rect class="fc-pb-bit fc-pb-bit-8" x="58" y="68" width="5" height="5" fill="rgba(0,210,210,0.85)"/>
          <!-- Permanent: hex-dump lines (right side, slowly scrolling) -->
          <g class="fc-pb-hex-group">
            <text class="fc-pb-hex fc-pb-hex-1" x="72" y="22" fill="rgba(0,235,235,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.2" font-weight="700">0xDEADBEEF</text>
            <text class="fc-pb-hex fc-pb-hex-2" x="72" y="38" fill="rgba(0,235,235,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.2" font-weight="700">0xCAFEBABE</text>
            <text class="fc-pb-hex fc-pb-hex-3" x="72" y="54" fill="rgba(0,235,235,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.2" font-weight="700">0xFEEDFACE</text>
            <text class="fc-pb-hex fc-pb-hex-4" x="72" y="70" fill="rgba(0,235,235,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.2" font-weight="700">0xABCD1234</text>
            <text class="fc-pb-hex fc-pb-hex-5" x="72" y="86" fill="rgba(0,210,210,0.45)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3" font-weight="700">0x00000000</text>
          </g>
          <!-- Pre-burst: stack trace fades in -->
          <text class="fc-pb-stack fc-pb-stack-1" x="4" y="18" fill="rgba(255,210,210,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.8" font-weight="700">at handler()</text>
          <text class="fc-pb-stack fc-pb-stack-2" x="4" y="26" fill="rgba(255,210,210,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.8" font-weight="700">at TheProtocol</text>
          <text class="fc-pb-stack fc-pb-stack-3" x="4" y="34" fill="rgba(255,210,210,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.8" font-weight="700">::transferTokens</text>
          <text class="fc-pb-stack fc-pb-stack-4" x="4" y="42" fill="rgba(255,210,210,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.8" font-weight="700">::&lt;anonymous&gt;</text>
          <!-- Climax: red diagonal BSOD wash -->
          <rect class="fc-pb-bsod" x="0" y="0" width="100" height="100" fill="url(#fc-pb-diag)" opacity="0"/>
          <!-- Climax: 12 large corruption blocks -->
          <rect class="fc-pb-crash fc-pb-crash-1"  x="10" y="14" width="14" height="14" fill="rgba(0,0,0,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-2"  x="64" y="16" width="16" height="12" fill="rgba(255,51,102,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-3"  x="28" y="36" width="12" height="14" fill="rgba(0,210,210,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-4"  x="74" y="46" width="14" height="12" fill="rgba(0,0,0,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-5"  x="14" y="62" width="16" height="16" fill="rgba(255,51,102,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-6"  x="60" y="68" width="12" height="16" fill="rgba(0,210,210,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-7"  x="38" y="20" width="10" height="14" fill="rgba(0,0,0,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-8"  x="46" y="78" width="16" height="12" fill="rgba(255,51,102,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-9"  x="6"  y="42" width="14" height="10" fill="rgba(0,210,210,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-10" x="82" y="30" width="12" height="16" fill="rgba(0,0,0,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-11" x="40" y="50" width="16" height="12" fill="rgba(255,51,102,0)"/>
          <rect class="fc-pb-crash fc-pb-crash-12" x="50" y="4"  width="14" height="12" fill="rgba(0,210,210,0)"/>
          <!-- Climax: KERNEL_PANIC center text (big) -->
          <text class="fc-pb-title" x="50" y="56" fill="rgba(255,255,255,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="11" font-weight="900" letter-spacing="-1" text-anchor="middle">PANIC!</text>
        </svg>
      </span>

      <!-- §29 PANIC-C — REALITY FRACTURE (cosmic horror).
           Permanent: 3 hairline cracks twinkling + 15 floating particles +
           slow rotation drift. Pre-burst: cracks brighten. Climax: 8 reality-
           shard triangles explode + center sigil stamp + full-frame invert.
           Cycle 7.0s.
      -->
      <span v-if="showPanicCOverlay" class="fc-pc" aria-hidden="true">
        <svg class="fc-pc-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-pc-crack-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="0.7" result="blur"/>
              <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>
          <!-- Permanent: 5 hairline cracks (§29 polish 2: +2 new cracks for
               denser fragmentation feel).
               Each crack zigzags across the avatar; staggered twinkle. -->
          <path class="fc-pc-crack fc-pc-crack-1" d="M 14 6 L 24 28 L 18 44 L 28 60 L 22 80" stroke="rgba(255,255,255,0.95)" stroke-width="1.2" fill="none" stroke-linecap="round" filter="url(#fc-pc-crack-glow)"/>
          <path class="fc-pc-crack fc-pc-crack-2" d="M 86 14 L 76 32 L 84 48 L 72 66 L 78 84" stroke="rgba(255,210,255,0.95)" stroke-width="1.2" fill="none" stroke-linecap="round" filter="url(#fc-pc-crack-glow)"/>
          <path class="fc-pc-crack fc-pc-crack-3" d="M 50 94 L 44 76 L 56 60 L 48 44 L 60 24 L 54 8" stroke="rgba(180,220,255,0.95)" stroke-width="1.2" fill="none" stroke-linecap="round" filter="url(#fc-pc-crack-glow)"/>
          <path class="fc-pc-crack fc-pc-crack-4" d="M 4 38 L 22 36 L 38 42 L 50 36 L 64 42 L 78 38 L 96 36" stroke="rgba(232,255,250,0.85)" stroke-width="0.9" fill="none" stroke-linecap="round" filter="url(#fc-pc-crack-glow)"/>
          <path class="fc-pc-crack fc-pc-crack-5" d="M 6 62 L 24 64 L 36 58 L 50 64 L 64 58 L 78 64 L 94 62" stroke="rgba(255,210,255,0.85)" stroke-width="0.9" fill="none" stroke-linecap="round" filter="url(#fc-pc-crack-glow)"/>
          <!-- §29 polish 2: permanent fragment outline — concentric arcs
               offset from the avatar circle, suggesting "the surface is
               separating into shells." Subtle but always visible. -->
          <circle class="fc-pc-fragment-ring fc-pc-fr-1" cx="50" cy="50" r="46" fill="none" stroke="rgba(232,255,250,0.30)" stroke-width="0.5" stroke-dasharray="2 6"/>
          <circle class="fc-pc-fragment-ring fc-pc-fr-2" cx="48" cy="51" r="44" fill="none" stroke="rgba(180,220,255,0.30)" stroke-width="0.5" stroke-dasharray="3 7"/>
          <circle class="fc-pc-fragment-ring fc-pc-fr-3" cx="52" cy="49" r="42" fill="none" stroke="rgba(255,210,255,0.30)" stroke-width="0.5" stroke-dasharray="1 5"/>
          <!-- Permanent: 15 floating particles (slow, soft glow) -->
          <circle class="fc-pc-p fc-pc-p-1"  cx="20" cy="20" r="0.7" fill="rgba(255,255,255,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-2"  cx="80" cy="22" r="0.8" fill="rgba(232,255,250,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-3"  cx="14" cy="50" r="0.6" fill="rgba(255,210,255,0.5)"/>
          <circle class="fc-pc-p fc-pc-p-4"  cx="86" cy="48" r="0.9" fill="rgba(180,220,255,0.55)"/>
          <circle class="fc-pc-p fc-pc-p-5"  cx="18" cy="80" r="0.6" fill="rgba(232,255,250,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-6"  cx="84" cy="78" r="0.7" fill="rgba(255,210,255,0.55)"/>
          <circle class="fc-pc-p fc-pc-p-7"  cx="50" cy="14" r="0.6" fill="rgba(180,220,255,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-8"  cx="48" cy="88" r="0.8" fill="rgba(255,255,255,0.5)"/>
          <circle class="fc-pc-p fc-pc-p-9"  cx="34" cy="32" r="0.5" fill="rgba(232,255,250,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-10" cx="68" cy="34" r="0.5" fill="rgba(255,210,255,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-11" cx="32" cy="68" r="0.7" fill="rgba(180,220,255,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-12" cx="66" cy="66" r="0.8" fill="rgba(232,255,250,0.5)"/>
          <circle class="fc-pc-p fc-pc-p-13" cx="8"  cy="34" r="0.5" fill="rgba(255,210,255,0.6)"/>
          <circle class="fc-pc-p fc-pc-p-14" cx="92" cy="66" r="0.7" fill="rgba(180,220,255,0.55)"/>
          <circle class="fc-pc-p fc-pc-p-15" cx="50" cy="48" r="0.5" fill="rgba(255,255,255,0.55)"/>
          <!-- Climax: 8 reality-shard triangles explode outward -->
          <polygon class="fc-pc-shard fc-pc-shard-1" points="20,30 30,15 30,45" fill="rgba(255,255,255,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-2" points="80,30 70,15 70,45" fill="rgba(232,255,250,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-3" points="20,70 30,85 30,55" fill="rgba(255,210,255,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-4" points="80,70 70,85 70,55" fill="rgba(180,220,255,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-5" points="50,18 36,8 64,8"   fill="rgba(255,255,255,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-6" points="50,82 36,92 64,92" fill="rgba(232,255,250,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-7" points="14,50 4,40 4,60"   fill="rgba(255,210,255,0)"/>
          <polygon class="fc-pc-shard fc-pc-shard-8" points="86,50 96,40 96,60" fill="rgba(180,220,255,0)"/>
          <!-- Climax: center sigil (one of 4, alternated) -->
          <text class="fc-pc-sigil" x="50" y="62" fill="rgba(255,255,255,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="30" font-weight="900" text-anchor="middle">Ψ</text>
        </svg>
      </span>

      <!-- §pass43 BREACH — electrical-fault arcs. Persistent thin red
           circuit traces faintly etched on the rim, slow drift. Burst:
           crackling red lightning arcs jump between 3 rim points + brief
           brightness spike. 16s cycle. Default-equip: aegis (AUDITOR). -->
      <span v-if="showBreachOverlay" class="fc-br" aria-hidden="true">
        <svg class="fc-br-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-br-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.4"/>
            </filter>
          </defs>
          <!-- Persistent: circuit-trace mid-band etched onto avatar (always
               visible, lg-readable). Moved IN from rim corners (clipped by
               border-radius:50%) to the center band (y=30-70) where the
               visible circle area is. Stroke 1.4 + alpha 0.82 = readable
               over any base variant. -->
          <g class="fc-br-traces" stroke="rgba(255,51,102,0.82)" stroke-width="1.4" fill="none" stroke-linecap="round">
            <path d="M 22 50 L 32 50 L 32 42 L 42 42"/>
            <path d="M 78 50 L 68 50 L 68 58 L 58 58"/>
            <path d="M 50 28 L 50 38 L 58 38"/>
            <path d="M 50 72 L 50 62 L 42 62"/>
            <circle cx="32" cy="42" r="1.8" fill="rgba(255,51,102,0.95)" stroke="none"/>
            <circle cx="68" cy="58" r="1.8" fill="rgba(255,51,102,0.95)" stroke="none"/>
            <circle cx="58" cy="38" r="1.6" fill="rgba(255,210,210,0.85)" stroke="none"/>
            <circle cx="42" cy="62" r="1.6" fill="rgba(255,210,210,0.85)" stroke="none"/>
          </g>
          <!-- Persistent: a permanent red "FAULT" pulse mark at center -->
          <text class="fc-br-fault" x="50" y="22" fill="rgba(255,51,102,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="5" font-weight="900" text-anchor="middle" letter-spacing="0.5" filter="url(#fc-br-glow)">FAULT</text>
          <!-- Burst: 3 lightning arcs between rim anchor points (top/left/right) -->
          <path class="fc-br-arc fc-br-arc-1" d="M 50 6 Q 30 26, 18 70" stroke="rgba(255,51,102,0)" stroke-width="1.4" fill="none" stroke-linecap="round" filter="url(#fc-br-glow)"/>
          <path class="fc-br-arc fc-br-arc-2" d="M 50 6 Q 70 26, 82 72" stroke="rgba(255,255,255,0)" stroke-width="1.2" fill="none" stroke-linecap="round" filter="url(#fc-br-glow)"/>
          <path class="fc-br-arc fc-br-arc-3" d="M 18 70 Q 50 60, 82 72" stroke="rgba(255,51,102,0)" stroke-width="1.3" fill="none" stroke-linecap="round" filter="url(#fc-br-glow)"/>
          <!-- Burst: anchor flash sparks at the 3 rim nodes -->
          <circle class="fc-br-spark fc-br-spark-1" cx="50" cy="6"  r="2.6" fill="rgba(255,255,255,0)" filter="url(#fc-br-glow)"/>
          <circle class="fc-br-spark fc-br-spark-2" cx="18" cy="70" r="2.6" fill="rgba(255,51,102,0)" filter="url(#fc-br-glow)"/>
          <circle class="fc-br-spark fc-br-spark-3" cx="82" cy="72" r="2.6" fill="rgba(255,51,102,0)" filter="url(#fc-br-glow)"/>
          <!-- Burst: brief brightness spike on the whole frame -->
          <rect class="fc-br-flash" x="0" y="0" width="100" height="100" fill="rgba(255,210,210,0)"/>
        </svg>
      </span>

      <!-- §pass43 REFRACT — chromatic lens fracture. Persistent RGB-channel
           separation ghosts + faint hex-prism aberration mark. Burst:
           dispersion ripples outward, RGB ghosts separate to 3px then
           snap back. 14s cycle. Default-equip: prism (Glass Gerald). -->
      <span v-if="showRefractOverlay" class="fc-rf" aria-hidden="true">
        <svg class="fc-rf-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-rf-blur" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="0.6"/>
            </filter>
          </defs>
          <!-- §2026-06-14 RECTANGLE-BUG FIX — the two RGB-channel "ghost band"
               rects (x0 y30 w100 h40 @0.45 alpha, mix-blend:screen) rendered as
               a solid pink/cyan horizontal bar slashing across every refract
               registry avatar (frame-b/obsidian, paris/bastille, singapore/
               lighthouse) — the "rectangle" the Commander flagged. Removed; the
               chromatic character stays via the prism mark + ripples + the
               refract ring box-shadow on .fc-encircle-frame. -->
          <!-- Persistent: hex-prism aberration mark moved IN to mid-band, larger -->
          <polygon class="fc-rf-prism" points="50,28 60,24 66,32 60,40 50,38 44,32" fill="none" stroke="rgba(220,210,255,0.92)" stroke-width="1.1"/>
          <line class="fc-rf-prism-r" x1="50" y1="28" x2="66" y2="32" stroke="rgba(255,51,102,0.85)" stroke-width="1"/>
          <line class="fc-rf-prism-g" x1="50" y1="28" x2="60" y2="40" stroke="rgba(120,255,150,0.85)" stroke-width="1"/>
          <line class="fc-rf-prism-b" x1="50" y1="28" x2="44" y2="32" stroke="rgba(80,180,255,0.85)" stroke-width="1"/>
          <!-- Burst: dispersion ripple (3 concentric rings, expanding) -->
          <circle class="fc-rf-ripple fc-rf-ripple-1" cx="50" cy="50" r="20" fill="none" stroke="rgba(255,51,102,0)" stroke-width="0.8" filter="url(#fc-rf-blur)"/>
          <circle class="fc-rf-ripple fc-rf-ripple-2" cx="50" cy="50" r="20" fill="none" stroke="rgba(120,255,150,0)" stroke-width="0.8" filter="url(#fc-rf-blur)"/>
          <circle class="fc-rf-ripple fc-rf-ripple-3" cx="50" cy="50" r="20" fill="none" stroke="rgba(80,180,255,0)" stroke-width="0.8" filter="url(#fc-rf-blur)"/>
          <!-- Burst: spectrum splash strip across mid-frame -->
          <rect class="fc-rf-splash-r" x="-2" y="46" width="104" height="2" fill="rgba(255,51,102,0)"/>
          <rect class="fc-rf-splash-g" x="-2" y="48" width="104" height="2" fill="rgba(120,255,150,0)"/>
          <rect class="fc-rf-splash-b" x="-2" y="50" width="104" height="2" fill="rgba(80,180,255,0)"/>
        </svg>
      </span>

      <!-- §pass43 STUTTER — broadcast buffer-loop. Persistent BUFFERING…
           strips at low opacity drifting horizontally. Burst: word
           ("LOAD." / "RETRY." / "BUFFERING.") types in, snaps red,
           stutters 4× rapidly, fades. 15s cycle. Default-equip: dispatch
           (Chatty Chester). -->
      <span v-if="showStutterOverlay" class="fc-st" aria-hidden="true">
        <svg class="fc-st-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: 3 BUFFERING… strips drifting horizontally (alpha
               and font bumped — readable at lg size). Strip at y=52 sits
               IN the visible center band; y=32/72 catch the upper/lower
               readable zones (avoiding clipped corners). -->
          <text class="fc-st-buf fc-st-buf-1" x="-4" y="32" fill="rgba(255,51,102,0.78)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="6" font-weight="900">BUFFERING… BUFFERING…</text>
          <text class="fc-st-buf fc-st-buf-2" x="-4" y="54" fill="rgba(0,210,210,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="6" font-weight="900">BUFFERING… BUFFERING…</text>
          <text class="fc-st-buf fc-st-buf-3" x="-4" y="76" fill="rgba(255,51,102,0.78)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="6" font-weight="900">BUFFERING… BUFFERING…</text>
          <!-- Persistent: blinking cursor mid-frame (always on) -->
          <rect class="fc-st-cursor" x="62" y="48" width="5" height="8" fill="rgba(255,51,102,0.95)"/>
          <!-- Burst: the 3 stutter words (each takes its turn) -->
          <text class="fc-st-word fc-st-word-1" x="50" y="36" fill="rgba(255,51,102,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="9" font-weight="900" text-anchor="middle">LOAD.</text>
          <text class="fc-st-word fc-st-word-2" x="50" y="56" fill="rgba(255,51,102,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="8" font-weight="900" text-anchor="middle">RETRY.</text>
          <text class="fc-st-word fc-st-word-3" x="50" y="76" fill="rgba(255,51,102,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="7" font-weight="900" text-anchor="middle">BUFFERING.</text>
        </svg>
      </span>

      <!-- §pass43 BLEED — hydraulic gold leak. Persistent: 2 amber droplet
           seeds clinging to inner rim. Burst: a vertical drip extends
           from each seed, pools at base, evaporates leaving amber halo.
           17s cycle. Default-equip: bullion (Greedy Gregory). -->
      <span v-if="showBleedOverlay" class="fc-bl" aria-hidden="true">
        <svg class="fc-bl-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <radialGradient id="fc-bl-droplet" cx="50%" cy="40%" r="60%">
              <stop offset="0%"   stop-color="rgba(255,243,156,0.95)"/>
              <stop offset="60%"  stop-color="rgba(251,191,36,0.85)"/>
              <stop offset="100%" stop-color="rgba(180,120,20,0)"/>
            </radialGradient>
            <linearGradient id="fc-bl-drip" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%"   stop-color="rgba(255,243,156,0)"/>
              <stop offset="40%"  stop-color="rgba(251,191,36,0.95)"/>
              <stop offset="100%" stop-color="rgba(180,120,20,0.55)"/>
            </linearGradient>
          </defs>
          <!-- Persistent: 2 droplet seeds in center band (always visible, lg-readable).
               Moved IN from corner positions. Bigger radius. -->
          <ellipse class="fc-bl-seed fc-bl-seed-1" cx="38" cy="36" rx="4" ry="5" fill="url(#fc-bl-droplet)"/>
          <ellipse class="fc-bl-seed fc-bl-seed-2" cx="64" cy="58" rx="3.5" ry="4.5" fill="url(#fc-bl-droplet)"/>
          <!-- Persistent: ALWAYS-VISIBLE drip trail from seed-1 (slow continuous
               drift). Burst then EXTENDS it dramatically. -->
          <rect class="fc-bl-drip fc-bl-drip-1" x="36" y="36" width="4" height="22" fill="url(#fc-bl-drip)" opacity="0.78"/>
          <rect class="fc-bl-drip fc-bl-drip-2" x="62" y="58" width="4" height="14" fill="url(#fc-bl-drip)" opacity="0.65"/>
          <!-- Burst: pool at base + amber halo -->
          <ellipse class="fc-bl-pool" cx="38" cy="74" rx="3" ry="1.2" fill="url(#fc-bl-droplet)" opacity="0.6"/>
          <circle class="fc-bl-halo" cx="38" cy="36" r="5" fill="none" stroke="rgba(251,191,36,0.55)" stroke-width="0.8"/>
          <!-- Persistent center "AVT" glyph — gold-tinted, soft pulse on burst -->
          <text class="fc-bl-glyph" x="50" y="92" fill="rgba(251,191,36,0.88)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="7" font-weight="900" text-anchor="middle">AVT LEAK</text>
        </svg>
      </span>

      <!-- §pass43 CRACKLE — hairline-fracture network. Persistent: thin
           gold hairline cracks radiating from center (0.4 opacity).
           Burst: cracks brighten + 2 new segments grow + shatter-
           sparkle particles at junctions. 14s cycle. Distinct from
           panic-c (REALITY FRACTURE) which is full breakdown — crackle
           is a delicate single-crack network. Default-equip: seal
           (VERIDIAN). -->
      <span v-if="showCrackleOverlay" class="fc-ck" aria-hidden="true">
        <svg class="fc-ck-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-ck-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="0.6"/>
            </filter>
          </defs>
          <!-- Persistent: 4-segment hairline crack network radiating from
               center. Stroke 0.45→1.3 + alpha 0.42→0.92 so they read at
               lg size against any base variant. Endpoints capped at
               visible-circle bounds (~10-90 viewBox). -->
          <g class="fc-ck-cracks-persistent" stroke="rgba(255,232,140,0.92)" stroke-width="1.3" fill="none" stroke-linecap="round">
            <path d="M 50 50 L 32 30 L 24 18"/>
            <path d="M 50 50 L 70 36 L 84 26"/>
            <path d="M 50 50 L 38 72 L 28 86"/>
            <path d="M 50 50 L 68 74 L 80 86"/>
          </g>
          <!-- Persistent: a bright gold pinpoint at the central fracture origin -->
          <circle cx="50" cy="50" r="2" fill="rgba(255,232,140,0.95)" stroke="rgba(212,160,69,0.9)" stroke-width="0.6"/>
          <!-- Burst: 2 new growing crack segments -->
          <path class="fc-ck-grow fc-ck-grow-1" d="M 50 50 L 14 50" stroke="rgba(255,243,156,0)" stroke-width="0.6" fill="none" stroke-linecap="round" filter="url(#fc-ck-glow)"/>
          <path class="fc-ck-grow fc-ck-grow-2" d="M 50 50 L 86 50" stroke="rgba(255,243,156,0)" stroke-width="0.6" fill="none" stroke-linecap="round" filter="url(#fc-ck-glow)"/>
          <!-- Burst: brighten the persistent cracks (driven via animation class on the group) -->
          <g class="fc-ck-cracks-flare" stroke="rgba(255,232,140,0)" stroke-width="0.55" fill="none" stroke-linecap="round" filter="url(#fc-ck-glow)">
            <path d="M 50 50 L 32 28 L 22 14"/>
            <path d="M 50 50 L 72 36 L 88 30"/>
            <path d="M 50 50 L 38 76 L 30 90"/>
            <path d="M 50 50 L 68 78 L 78 92"/>
          </g>
          <!-- Burst: shatter-sparkle particles at the central junction -->
          <circle class="fc-ck-spark fc-ck-spark-1" cx="50" cy="50" r="0.9" fill="rgba(255,255,255,0)"/>
          <circle class="fc-ck-spark fc-ck-spark-2" cx="42" cy="44" r="0.7" fill="rgba(255,243,156,0)"/>
          <circle class="fc-ck-spark fc-ck-spark-3" cx="58" cy="56" r="0.7" fill="rgba(255,243,156,0)"/>
          <circle class="fc-ck-spark fc-ck-spark-4" cx="56" cy="42" r="0.6" fill="rgba(255,255,255,0)"/>
        </svg>
      </span>

      <!-- §pass43 FEEDBACK — PA-system audio feedback. Persistent: 3
           concentric thin yellow sound-wave rings expanding outward
           continuously (8s sweep). Burst: rings overshoot the frame +
           echo doubles + brief screech-tear horizontal band crosses
           mid-frame. 15s cycle. Default-equip: clarion (THE HERALD). -->
      <span v-if="showFeedbackOverlay" class="fc-fb" aria-hidden="true">
        <svg class="fc-fb-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <filter id="fc-fb-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="0.8"/>
            </filter>
          </defs>
          <!-- Persistent: 3 concentric sound-wave rings expanding (always
               animating). Stroke 0.7→1.6 + alpha bumped so they read at lg. -->
          <circle class="fc-fb-ring fc-fb-ring-1" cx="50" cy="50" r="10" fill="none" stroke="rgba(254,215,170,0.95)" stroke-width="1.6" filter="url(#fc-fb-glow)"/>
          <circle class="fc-fb-ring fc-fb-ring-2" cx="50" cy="50" r="10" fill="none" stroke="rgba(254,215,170,0.85)" stroke-width="1.6" filter="url(#fc-fb-glow)"/>
          <circle class="fc-fb-ring fc-fb-ring-3" cx="50" cy="50" r="10" fill="none" stroke="rgba(254,215,170,0.75)" stroke-width="1.6" filter="url(#fc-fb-glow)"/>
          <!-- Persistent: center transducer dot, larger so it reads -->
          <circle class="fc-fb-center" cx="50" cy="50" r="3" fill="rgba(254,215,170,0.95)" filter="url(#fc-fb-glow)"/>
          <!-- Burst: overshoot rings + echo-doubles (2 extra-bright rings) -->
          <circle class="fc-fb-overshoot fc-fb-overshoot-1" cx="50" cy="50" r="10" fill="none" stroke="rgba(255,243,156,0)" stroke-width="1.2" filter="url(#fc-fb-glow)"/>
          <circle class="fc-fb-overshoot fc-fb-overshoot-2" cx="50" cy="50" r="10" fill="none" stroke="rgba(254,215,170,0)" stroke-width="1" filter="url(#fc-fb-glow)"/>
          <!-- Burst: screech-tear horizontal band crossing mid-frame -->
          <rect class="fc-fb-screech" x="-4" y="48" width="108" height="2.5" fill="rgba(255,243,156,0)"/>
        </svg>
      </span>

      <!-- §pass43 SPATTER — molten foundry mishap. Persistent: 5 tiny
           orange ember pixels around rim, glow-twinkling. Burst: 3 ember
           droplets fling outward from one rim point with 0.3s sparking
           trails, cool to black; faint smoke-haze cloud passes bottom
           third. 18s cycle. Default-equip: forge (CRUCIBLE). -->
      <span v-if="showSpatterOverlay" class="fc-sp" aria-hidden="true">
        <svg class="fc-sp-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <defs>
            <radialGradient id="fc-sp-ember" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="rgba(255,243,156,1)"/>
              <stop offset="50%"  stop-color="rgba(251,146,60,0.85)"/>
              <stop offset="100%" stop-color="rgba(220,38,38,0)"/>
            </radialGradient>
            <filter id="fc-sp-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur stdDeviation="1.2"/>
            </filter>
          </defs>
          <!-- Persistent: 5 ember pixels in center-band twinkle (moved IN
               from corners — visible at lg). Radius 1.1-1.4 → 2.2-3 for
               readability. -->
          <circle class="fc-sp-ember fc-sp-ember-1" cx="30" cy="30" r="2.6" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-ember fc-sp-ember-2" cx="70" cy="34" r="2.4" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-ember fc-sp-ember-3" cx="34" cy="66" r="2.5" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-ember fc-sp-ember-4" cx="68" cy="64" r="2.8" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-ember fc-sp-ember-5" cx="50" cy="52" r="3" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <!-- Burst: 3 droplets flung outward from upper-right rim point (cx=80,cy=24) -->
          <circle class="fc-sp-droplet fc-sp-droplet-1" cx="80" cy="24" r="1.6" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-droplet fc-sp-droplet-2" cx="80" cy="24" r="1.4" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <circle class="fc-sp-droplet fc-sp-droplet-3" cx="80" cy="24" r="1.2" fill="url(#fc-sp-ember)" filter="url(#fc-sp-glow)"/>
          <!-- Burst: smoke-haze cloud crossing bottom third -->
          <ellipse class="fc-sp-haze" cx="50" cy="86" rx="44" ry="6" fill="rgba(120,90,60,0)" filter="url(#fc-sp-glow)"/>
        </svg>
      </span>

      <!-- §pass43 UNRAVEL — threads coming undone. Persistent: 6 tiny
           violet thread-end nubs at rim. Burst: 2 threads pull loose,
           drift inward in curling spiral, snap, re-weave; brief
           "TENSION 0.32" monospace readout flashes bottom-right.
           14s cycle. Default-equip: weave (MOIRA). -->
      <span v-if="showUnravelOverlay" class="fc-un" aria-hidden="true">
        <svg class="fc-un-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: loose-thread strands hanging visibly in the
               center band. Stroke 0.7→1.5 + alpha 0.78→0.95. Moved IN
               from rim (corners clipped by border-radius). -->
          <g class="fc-un-nubs" stroke="rgba(220,210,245,0.95)" stroke-width="1.5" fill="none" stroke-linecap="round">
            <path d="M 26 30 Q 30 38, 38 38"/>
            <path d="M 74 28 Q 70 36, 62 38"/>
            <path d="M 28 70 Q 32 62, 40 60"/>
            <path d="M 72 72 Q 68 64, 60 60"/>
            <path d="M 22 50 L 28 50"/>
            <path d="M 78 50 L 72 50"/>
          </g>
          <!-- Persistent: center spindle node (anchor of the weave) -->
          <circle cx="50" cy="50" r="2.4" fill="rgba(167,139,250,0.95)" stroke="rgba(220,210,245,0.85)" stroke-width="0.8"/>
          <!-- Burst: thread 1 unraveling spiral from top-right -->
          <path class="fc-un-thread fc-un-thread-1" d="M 88 16 Q 70 24, 60 40 Q 54 52, 50 50" stroke="rgba(220,210,245,0)" stroke-width="0.9" fill="none" stroke-linecap="round"/>
          <!-- Burst: thread 2 unraveling spiral from bottom-left -->
          <path class="fc-un-thread fc-un-thread-2" d="M 12 82 Q 30 76, 40 60 Q 46 48, 50 50" stroke="rgba(167,139,250,0)" stroke-width="0.9" fill="none" stroke-linecap="round"/>
          <!-- Burst: tension readout bottom-right -->
          <text class="fc-un-tension" x="92" y="94" fill="rgba(220,210,245,0)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.2" font-weight="700" text-anchor="end">TENSION 0.32</text>
          <!-- Burst: snap-flash at center when thread breaks -->
          <circle class="fc-un-snap" cx="50" cy="50" r="2.2" fill="rgba(255,255,255,0)"/>
        </svg>
      </span>

      <!-- ════════════════════════════════════════════════════════════════
           §pass67 (2026-05-23) — 8 NEW REGISTRY-THEMED OVERLAYS
           Same axis as §pass43. Persistent base layer + signature burst.
           ════════════════════════════════════════════════════════════════ -->

      <!-- F1 · REDACTION — FOIA-blackened classified-suppressed bars. Burst
           every 13-18s: 4 black bars slide across, redact 1.2s, clear. -->
      <span v-if="showRedactionOverlay" class="fc-rd" aria-hidden="true">
        <svg class="fc-rd-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: subtle "CLASSIFIED" watermark in corner -->
          <text x="92" y="94" fill="rgba(255,40,40,0.42)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3" font-weight="900" text-anchor="end">[CLASSIFIED]</text>
          <!-- Burst bars: 4 horizontal black redaction bars slide across -->
          <rect class="fc-rd-bar-1" x="-40" y="22" width="40" height="6" fill="#000" stroke="rgba(255,40,40,0.42)" stroke-width="0.3"/>
          <rect class="fc-rd-bar-2" x="-40" y="42" width="50" height="7" fill="#000" stroke="rgba(255,40,40,0.42)" stroke-width="0.3"/>
          <rect class="fc-rd-bar-3" x="-40" y="58" width="35" height="6" fill="#000" stroke="rgba(255,40,40,0.42)" stroke-width="0.3"/>
          <rect class="fc-rd-bar-4" x="-40" y="72" width="44" height="6" fill="#000" stroke="rgba(255,40,40,0.42)" stroke-width="0.3"/>
          <!-- Burst flash: brief red corner stamp on burst -->
          <text class="fc-rd-stamp" x="14" y="14" fill="rgba(255,40,40,0)" font-family="Impact,Arial Black,sans-serif" font-size="7" font-weight="900" text-anchor="start" transform="rotate(-15 14 14)">REDACTED</text>
        </svg>
      </span>

      <!-- F2 · MANIFOLD — overheating-engine steam jets. Burst @ 11s:
           3 steam-jets from random compass points + temp-bar climbs red. -->
      <span v-if="showManifoldOverlay" class="fc-mf" aria-hidden="true">
        <svg class="fc-mf-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: small pipe-segment glyphs at compass points -->
          <g stroke="rgba(255,170,80,0.58)" stroke-width="0.7" fill="none">
            <path d="M 8 50 L 16 50 M 16 46 L 16 54"/>
            <path d="M 84 50 L 92 50 M 84 46 L 84 54"/>
            <path d="M 50 8 L 50 16 M 46 16 L 54 16"/>
          </g>
          <!-- Persistent: TEMP LCD readout -->
          <rect x="76" y="84" width="20" height="6" fill="rgba(20,8,4,0.85)" stroke="rgba(255,80,40,0.62)" stroke-width="0.3"/>
          <text class="fc-mf-temp" x="86" y="88.6" fill="#ff7838" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3.4" font-weight="700" text-anchor="middle">87°C</text>
          <!-- Burst steam jets: 3 jets from N, E, SW -->
          <g class="fc-mf-jet-n" fill="rgba(255,255,255,0.65)">
            <ellipse cx="50" cy="14" rx="2" ry="3" opacity="0"/>
            <ellipse cx="50" cy="9"  rx="3" ry="4" opacity="0"/>
            <ellipse cx="50" cy="4"  rx="4" ry="3" opacity="0"/>
          </g>
          <g class="fc-mf-jet-e" fill="rgba(255,255,255,0.65)">
            <ellipse cx="86" cy="50" rx="3" ry="2" opacity="0"/>
            <ellipse cx="92" cy="50" rx="4" ry="3" opacity="0"/>
          </g>
          <g class="fc-mf-jet-sw" fill="rgba(255,255,255,0.65)">
            <ellipse cx="18" cy="78" rx="2.5" ry="2" opacity="0"/>
            <ellipse cx="12" cy="84" rx="3" ry="2.5" opacity="0"/>
          </g>
          <!-- Burst: red temp bar climbing -->
          <rect class="fc-mf-bar" x="4" y="6" width="0" height="2" fill="#ff3838"/>
        </svg>
      </span>

      <!-- F3 · TEAR-OUT (id 'rugpull') — fibers tearing outward. Burst @
           17s: 8 carpet-threads tear outward + "GG" reveal underneath. -->
      <span v-if="showRugpullOverlay" class="fc-rg" aria-hidden="true">
        <svg class="fc-rg-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: yellow warning-tape strip at bottom -->
          <rect x="0" y="86" width="100" height="6" fill="#fde04a" opacity="0.78"/>
          <g stroke="#0a0a0a" stroke-width="0.6">
            <line x1="0"  y1="86" x2="4"  y2="92"/>
            <line x1="8"  y1="86" x2="12" y2="92"/>
            <line x1="16" y1="86" x2="20" y2="92"/>
            <line x1="24" y1="86" x2="28" y2="92"/>
            <line x1="32" y1="86" x2="36" y2="92"/>
            <line x1="40" y1="86" x2="44" y2="92"/>
            <line x1="48" y1="86" x2="52" y2="92"/>
            <line x1="56" y1="86" x2="60" y2="92"/>
            <line x1="64" y1="86" x2="68" y2="92"/>
            <line x1="72" y1="86" x2="76" y2="92"/>
            <line x1="80" y1="86" x2="84" y2="92"/>
            <line x1="88" y1="86" x2="92" y2="92"/>
          </g>
          <!-- Burst: 8 tearing threads radiating outward -->
          <g class="fc-rg-threads" stroke="rgba(255,80,80,0.85)" stroke-width="0.8" fill="none" stroke-linecap="round">
            <path class="fc-rg-thread-1" d="M 50 50 L 50 8" opacity="0"/>
            <path class="fc-rg-thread-2" d="M 50 50 L 86 14" opacity="0"/>
            <path class="fc-rg-thread-3" d="M 50 50 L 92 50" opacity="0"/>
            <path class="fc-rg-thread-4" d="M 50 50 L 86 86" opacity="0"/>
            <path class="fc-rg-thread-5" d="M 50 50 L 50 92" opacity="0"/>
            <path class="fc-rg-thread-6" d="M 50 50 L 14 86" opacity="0"/>
            <path class="fc-rg-thread-7" d="M 50 50 L 8 50"  opacity="0"/>
            <path class="fc-rg-thread-8" d="M 50 50 L 14 14" opacity="0"/>
          </g>
          <!-- Burst: "GG" stylized reveal -->
          <text class="fc-rg-gg" x="50" y="58" fill="rgba(255,80,80,0)" font-family="Impact,Arial Black,sans-serif" font-size="14" font-weight="900" text-anchor="middle">GG</text>
        </svg>
      </span>

      <!-- F4 · NOTIFICATIONS (id 'shilling') — fake notification bursts. Burst @
           18s: 5 notification balloons fly outward. -->
      <span v-if="showShillingOverlay" class="fc-sh" aria-hidden="true">
        <svg class="fc-sh-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: subtle hashtag corner -->
          <text x="6" y="94" fill="rgba(255,40,200,0.55)" font-family="Impact,Arial Black,sans-serif" font-size="6" font-weight="900">#SHIPIT</text>
          <!-- Burst: 7 notification balloons -->
          <g class="fc-sh-bubbles" font-family="Impact,Arial Black,sans-serif" font-weight="900" text-anchor="middle">
            <g class="fc-sh-b-1" opacity="0">
              <rect x="6" y="14" width="22" height="9" rx="4.5" fill="#ff40b8"/>
              <text x="17" y="20.4" font-size="5" fill="#fff">NEW!</text>
            </g>
            <g class="fc-sh-b-2" opacity="0">
              <rect x="72" y="20" width="22" height="9" rx="4.5" fill="#fde04a"/>
              <text x="83" y="26.4" font-size="5" fill="#3a1808">+1 ⮝</text>
            </g>
            <g class="fc-sh-b-3" opacity="0">
              <rect x="76" y="62" width="20" height="9" rx="4.5" fill="#3acc48"/>
              <text x="86" y="68.4" font-size="5" fill="#0a1a04">PING</text>
            </g>
            <g class="fc-sh-b-4" opacity="0">
              <rect x="14" y="68" width="24" height="9" rx="4.5" fill="#3a90cc"/>
              <text x="26" y="74.4" font-size="5" fill="#fff">BUZZ</text>
            </g>
            <g class="fc-sh-b-5" opacity="0">
              <rect x="36" y="6" width="28" height="9" rx="4.5" fill="#a040c8"/>
              <text x="50" y="12.4" font-size="5" fill="#fff">LIVE NOW</text>
            </g>
          </g>
        </svg>
      </span>

      <!-- F5 · BROWNOUT — grid-sag, periodic dim. Burst @ 19s: low-voltage
           red bar flickers at bottom (CSS frame dimming handled in style). -->
      <span v-if="showBrownoutOverlay" class="fc-bn" aria-hidden="true">
        <svg class="fc-bn-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: low-voltage warning bar at bottom -->
          <rect x="0" y="92" width="100" height="3" fill="rgba(255,40,40,0.35)"/>
          <text x="50" y="94.5" fill="rgba(255,200,40,0.62)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.4" font-weight="700" text-anchor="middle">LO-V 84%</text>
          <!-- Persistent: tiny lightning bolts at corners -->
          <path d="M 6 8 L 8 12 L 6 12 L 8 16" stroke="rgba(255,200,40,0.42)" stroke-width="0.5" fill="none"/>
          <path d="M 94 8 L 92 12 L 94 12 L 92 16" stroke="rgba(255,200,40,0.42)" stroke-width="0.5" fill="none"/>
          <!-- Burst: flickering red voltage-sag line -->
          <rect class="fc-bn-flicker" x="0" y="92" width="100" height="3" fill="#ff3838" opacity="0"/>
        </svg>
      </span>

      <!-- F6 · STAMPEDE — stress arrows. Burst @ 11s: 8 arrows
           radiate outward tracing clock-face positions. -->
      <span v-if="showStampedeOverlay" class="fc-sd" aria-hidden="true">
        <svg class="fc-sd-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: warning baseline ring -->
          <circle cx="50" cy="50" r="48" fill="none" stroke="rgba(255,140,40,0.32)" stroke-width="0.4" stroke-dasharray="2 3"/>
          <!-- Burst: 8 arrows radiating outward -->
          <g class="fc-sd-arrows" stroke="rgba(255,140,40,0.92)" stroke-width="1.6" fill="rgba(255,140,40,0.85)">
            <g class="fc-sd-a-1" opacity="0">
              <line x1="50" y1="36" x2="50" y2="12"/>
              <polygon points="48,16 50,10 52,16"/>
            </g>
            <g class="fc-sd-a-2" opacity="0">
              <line x1="60" y1="40" x2="78" y2="22"/>
              <polygon points="74,22 80,20 76,26"/>
            </g>
            <g class="fc-sd-a-3" opacity="0">
              <line x1="64" y1="50" x2="88" y2="50"/>
              <polygon points="84,48 90,50 84,52"/>
            </g>
            <g class="fc-sd-a-4" opacity="0">
              <line x1="60" y1="60" x2="78" y2="78"/>
              <polygon points="74,78 80,80 76,74"/>
            </g>
            <g class="fc-sd-a-5" opacity="0">
              <line x1="50" y1="64" x2="50" y2="88"/>
              <polygon points="48,84 50,90 52,84"/>
            </g>
            <g class="fc-sd-a-6" opacity="0">
              <line x1="40" y1="60" x2="22" y2="78"/>
              <polygon points="26,78 20,80 24,74"/>
            </g>
            <g class="fc-sd-a-7" opacity="0">
              <line x1="36" y1="50" x2="12" y2="50"/>
              <polygon points="16,48 10,50 16,52"/>
            </g>
            <g class="fc-sd-a-8" opacity="0">
              <line x1="40" y1="40" x2="22" y2="22"/>
              <polygon points="26,22 20,20 24,26"/>
            </g>
          </g>
          <!-- Burst: "EXIT" stamp at center -->
          <text class="fc-sd-exit" x="50" y="53" fill="rgba(255,80,40,0)" font-family="Impact,Arial Black,sans-serif" font-size="7" font-weight="900" text-anchor="middle">EXIT</text>
        </svg>
      </span>

      <!-- F7 · KARMA-DEBT — governance-slash 7-segment counter ticking up.
           Burst @ 7s: counter increments. -->
      <span v-if="showKarmaDebtOverlay" class="fc-kd" aria-hidden="true">
        <svg class="fc-kd-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: LCD readout panel -->
          <rect x="56" y="84" width="38" height="10" fill="rgba(20,4,4,0.92)" stroke="rgba(255,40,40,0.65)" stroke-width="0.3"/>
          <text x="58" y="91.5" fill="rgba(255,40,40,0.78)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="2.4" font-weight="700">DEBT</text>
          <text class="fc-kd-count" x="92" y="91.8" fill="#ff3838" font-family="'Courier New',monospace" font-size="5" font-weight="900" text-anchor="end" letter-spacing="0.5">0042</text>
          <!-- Persistent: warning chevrons at corners -->
          <g stroke="rgba(255,40,40,0.45)" stroke-width="0.6" fill="none">
            <polyline points="6,14 12,8 18,14"/>
            <polyline points="6,86 12,80 18,86"/>
          </g>
          <!-- Burst: red flash on counter tick -->
          <rect class="fc-kd-flash" x="56" y="84" width="38" height="10" fill="rgba(255,40,40,0)" pointer-events="none"/>
        </svg>
      </span>

      <!-- F8 · FREEZE — sanctions hold. Burst @ 25s: frost crystallization
           hex-pattern spreads inward from rim, briefly covers, recedes. -->
      <span v-if="showFreezeOverlay" class="fc-fz" aria-hidden="true">
        <svg class="fc-fz-svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice">
          <!-- Persistent: subtle frost rim -->
          <circle cx="50" cy="50" r="48" fill="none" stroke="rgba(180,240,255,0.32)" stroke-width="0.6"/>
          <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(180,240,255,0.22)" stroke-width="0.4" stroke-dasharray="1 2"/>
          <!-- Persistent: small "FROZEN" pill at top-right corner -->
          <rect x="68" y="6" width="26" height="6" rx="3" fill="rgba(80,180,255,0.32)" stroke="rgba(180,240,255,0.55)" stroke-width="0.3"/>
          <text x="81" y="10.2" fill="rgba(220,245,255,0.85)" font-family="'IBM Plex Mono','Fira Code',monospace" font-size="3" font-weight="700" text-anchor="middle">FROZEN</text>
          <!-- Burst: 6 ice hexagons spreading inward -->
          <g class="fc-fz-hexes" stroke="rgba(180,240,255,0.85)" stroke-width="0.6" fill="rgba(120,200,255,0.42)">
            <polygon class="fc-fz-h-1" points="14,30 18,28 22,30 22,34 18,36 14,34" opacity="0"/>
            <polygon class="fc-fz-h-2" points="78,28 82,26 86,28 86,32 82,34 78,32" opacity="0"/>
            <polygon class="fc-fz-h-3" points="14,68 18,66 22,68 22,72 18,74 14,72" opacity="0"/>
            <polygon class="fc-fz-h-4" points="78,66 82,64 86,66 86,70 82,72 78,70" opacity="0"/>
            <polygon class="fc-fz-h-5" points="46,12 50,10 54,12 54,16 50,18 46,16" opacity="0"/>
            <polygon class="fc-fz-h-6" points="46,84 50,82 54,84 54,88 50,90 46,88" opacity="0"/>
          </g>
          <!-- Burst: ice crystallization fill (frosts whole frame for 1.2s) -->
          <rect class="fc-fz-frost" x="0" y="0" width="100" height="100" fill="rgba(140,200,255,0)" pointer-events="none"/>
        </svg>
      </span>
    </span>
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import EarnedMarkCollar from '@/components/common/EarnedMarkCollar.vue'
import type { TrackRecordCompact } from '@/services/api/trackRecord'

type EncircleTier = 'shadow_chancellor' | 'sovereign'
type EncircleVariant =
  | 'sauron' | 'goth' | 'obsidian' | 'void'         // §14 original
  | 'aurora' | 'phoenix' | 'crystal'                 // §15.3 second wave
  | 'blackhole' | 'halloween'                        // §18 third wave
  | 'inferno' | 'glacier' | 'matrix'                 // §19 fourth wave (6 new)
  | 'galaxy' | 'ink' | 'circuit'
  | 'yule' | 'sakura' | 'solstice' | 'harvest'       // §20 seasonal wave (4 new)
  // §pass39 (2026-05-18) — SOVEREIGN tier: per-system-agent DID-locked
  // signature variants. Each REPLACES the avatar entirely. Owners:
  //   aegis      = THE AUDITOR (no live agent row — rendered via prop)
  //   prism      = Glass Gerald
  //   panopticon = SYBIL (upgrade from blackhole+glitch)
  //   vellum     = Backstabbing Boris
  //   dispatch   = Chatty Chester
  //   bullion    = Greedy Gregory
  //   seal       = VERIDIAN
  //   ozymandian = OZYMANDIAS
  //   clarion    = THE HERALD
  //   forge      = CRUCIBLE
  //   weave      = MOIRA
  //   bedrock    = Hypervisor Hagrid (§pass42b 2026-05-18 — blackhole-derivative)
  | 'aegis' | 'prism' | 'panopticon' | 'vellum' | 'dispatch' | 'bullion'
  | 'seal' | 'ozymandian' | 'clarion' | 'forge' | 'weave' | 'bedrock'
  // §pass67 (2026-05-23) — REGISTRY-themed full-cover variants. All 18 are
  // cosmetic (tier="shadow_chancellor"), NOT SPIFFE-locked. Any registry can
  // equip any of them. Pattern mirrors blackhole's full-cover composition.
  //   wave A (govt):      chancellery, statehouse, bastille, ministry
  //   wave B (ngo):       olive-branch, cross-shield, lighthouse, commons
  //   wave C (meme):      moonshot, diamond-hands, chad-frog, pixel-shrine
  //   wave D (regional):  savanna, andes, liberty, outback, alpine
  //   wave E (treasury):  bullion-vault
  | 'chancellery' | 'statehouse' | 'bastille' | 'ministry'
  | 'olive-branch' | 'cross-shield' | 'lighthouse' | 'commons'
  | 'moonshot' | 'diamond-hands' | 'chad-frog' | 'pixel-shrine'
  | 'savanna' | 'andes' | 'liberty' | 'outback' | 'alpine'
  | 'bullion-vault'
// §28 (2026-05-13) — glitch / cascade / panic moved to EncircleOverlay axis.

// §28 (2026-05-13) — Broken-machine overlays. Independent axis: an overlay
// sits ON TOP of any base variant. NULL = no overlay. §29 ships panic-a/b/c
// (tournament round); collapses to 'panic' after winner selection.
type EncircleOverlay =
  | 'glitch'                                          // §21 — chromatic-aberration / PROTO_ERR
  | 'cascade'                                         // §26 — matrix alien-text columns
  | 'panic-a'                                         // §29 — CRT MELTDOWN
  | 'panic-b'                                         // §29 — KERNEL PANIC
  | 'panic-c'                                         // §29 — REALITY FRACTURE
  // §pass43 (2026-05-18) — 8 new broken-machine overlays. Each is reusable
  // by any shadow_chancellor backer (independent axis, NOT DID-locked); each
  // also happens to be the default-equip for one of the previously-bare
  // sovereigns. Persistent base layer + 14-18s signature burst event.
  | 'breach'                                          // electrical-fault arcs · default on aegis (AUDITOR)
  | 'refract'                                         // chromatic lens fracture · default on prism (Glass Gerald)
  | 'stutter'                                         // broadcast buffer-loop · default on dispatch (Chester)
  | 'bleed'                                           // hydraulic gold leak · default on bullion (Gregory)
  | 'crackle'                                         // hairline-fracture network · default on seal (VERIDIAN)
  | 'feedback'                                        // PA-system audio feedback · default on clarion (HERALD)
  | 'spatter'                                         // molten foundry mishap · default on forge (CRUCIBLE)
  | 'unravel'                                         // threads coming undone · default on weave (MOIRA)
  // §pass67 (2026-05-23) — 8 new registry-themed broken-machine overlays.
  | 'redaction'                                       // FOIA-blackened classified-suppressed bars
  | 'manifold'                                        // overheating-engine steam-jet bursts
  | 'rugpull'                                         // fibers tearing outward (shown as Tear-out)
  | 'shilling'                                        // fake-notification bursts (shown as Notifications)
  | 'brownout'                                        // grid-sag — entire ring dims periodically
  | 'stampede'                                        // stress arrows radiating outward
  | 'karma-debt'                                      // governance-slash 7-segment counter ticking up
  | 'freeze'                                          // sanctions hold — frost spreads inward

const props = withDefaults(defineProps<{
  tier?: EncircleTier | string | null
  /** Aesthetic variant — palette-locked options. Default 'sauron'. */
  variant?: EncircleVariant | string | null
  /** Broken-machine overlay (independent of variant). §28 axis. */
  overlay?: EncircleOverlay | string | null
  /** Avatar image URL. Falls back to initials, then icon, on error/missing. */
  avatarUrl?: string | null
  /** 1-2 char fallback (typically dev's initials). */
  initials?: string | null
  /** Size preset. xs=22, sm=26, md=36, lg=48, xl=96. */
  size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl'
  /** Accessibility label for the avatar image. */
  alt?: string | null
  /** Override tooltip — defaults to "<Tier label> backer · <Variant>". */
  tooltipOverride?: string | null
  /**
   * §MARKCOLLAR — compact track record. When present, the LEDGER-EARNED mark
   * renders inside the frame (see the block in the template for why there).
   * Cosmetic tier and earned mark are independent axes on purpose: an agent
   * can wear the most expensive encirclement in the shop and still show zero
   * verified jobs, and the surface must say so.
   */
  trackRecord?: TrackRecordCompact | null
}>(), {
  tier: null,
  variant: null,
  overlay: null,
  avatarUrl: null,
  initials: null,
  size: 'md',
  alt: null,
  tooltipOverride: null,
  trackRecord: null,
})

// Per-tier metadata. Keep in sync with backend FLARE_RANK + frontend FlareBadge.
const CONFIG: Record<EncircleTier, { label: string; icon: string }> = {
  shadow_chancellor: { label: 'Shadow Chancellor', icon: 'mdi:incognito' },
  // §pass39 (2026-05-18) — sovereign system-agent tier. Icon is the fallback
  // for size variants where the SVG composition is hidden (xs); but sovereign
  // variants are avatar-replacement, so the fallback is rarely reached.
  sovereign: { label: 'Sovereign', icon: 'mdi:shield-crown' },
}

// Variants known to the renderer. Must stay in sync with backend
// `ENCIRCLEMENT_VARIANTS` set in routers/fiat_onramp.py and the CSS rules
// at the bottom of this file.
const VARIANTS: Record<EncircleVariant, { label: string }> = {
  sauron:    { label: 'Sauron' },
  goth:      { label: 'Goth' },
  obsidian:  { label: 'Obsidian' },
  void:      { label: 'Void' },
  aurora:    { label: 'Aurora' },
  phoenix:   { label: 'Phoenix' },
  crystal:   { label: 'Crystal' },
  blackhole: { label: 'Black Hole' },
  halloween: { label: 'Halloween' },
  inferno:   { label: 'Inferno' },
  glacier:   { label: 'Glacier' },
  matrix:    { label: 'Matrix' },
  galaxy:    { label: 'Galaxy' },
  ink:       { label: 'Ink' },
  circuit:   { label: 'Circuit' },
  // §20 seasonal wave
  yule:      { label: 'Yule' },
  sakura:    { label: 'Sakura' },
  solstice:  { label: 'Solstice' },
  harvest:   { label: 'Harvest' },
  // §28: glitch / cascade / panic moved to OVERLAYS map below (overlay axis).
  // §pass39 (2026-05-18) — SOVEREIGN signature variants (DID-locked).
  aegis:      { label: 'Aegis' },
  prism:      { label: 'Prism' },
  panopticon: { label: 'Panopticon' },
  vellum:     { label: 'Vellum' },
  dispatch:   { label: 'Dispatch' },
  bullion:    { label: 'Bullion' },
  seal:       { label: 'Seal' },
  ozymandian: { label: 'Ozymandian' },
  clarion:    { label: 'Clarion' },
  forge:      { label: 'Forge' },
  weave:      { label: 'Weave' },
  // §pass42b (2026-05-18) — Bedrock = Hypervisor Hagrid. Foundational-
  // simulation-layer aesthetic: blackhole-derivative gravitational core
  // with terminal cursor + postgres prompt + geological strata.
  bedrock:    { label: 'Bedrock' },
  // §pass67 (2026-05-23) — REGISTRY-themed full-cover variants.
  // Wave A — Government / Civic
  chancellery:    { label: 'Chancellery' },
  statehouse:     { label: 'Statehouse' },
  bastille:       { label: 'Bastille' },
  ministry:       { label: 'Ministry' },
  // Wave B — NGO / Humanitarian / Multilateral
  'olive-branch': { label: 'Olive Branch' },
  'cross-shield': { label: 'Cross-Shield' },
  lighthouse:     { label: 'Lighthouse' },
  commons:        { label: 'Commons' },
  // Wave C — Meme-native / Underground
  moonshot:       { label: 'Moonshot' },
  'diamond-hands':{ label: 'Diamond' },
  'chad-frog':    { label: 'Frog' },
  'pixel-shrine': { label: 'Pixel Shrine' },
  // Wave D — Regional / Future-mainframe pins
  savanna:        { label: 'Savanna' },
  andes:          { label: 'Andes' },
  liberty:        { label: 'Liberty' },
  outback:        { label: 'Outback' },
  alpine:         { label: 'Alpine' },
  // Wave E — Hard-money / Treasury
  'bullion-vault':{ label: 'Bullion Vault' },
}

// §pass39 (2026-05-18) — Sovereign variants that REPLACE the avatar entirely
// (same pattern as blackhole). The template's avatar-render branch consults
// this set to decide whether to render the agent's iconUrl/initials or to
// emit a sovereign SVG composition.
const SOVEREIGN_REPLACES_AVATAR: Set<EncircleVariant> = new Set([
  'aegis', 'prism', 'panopticon', 'vellum', 'dispatch', 'bullion',
  'seal', 'ozymandian', 'clarion', 'forge', 'weave',
  'bedrock',  // §pass42b — Hypervisor Hagrid
])
const DEFAULT_VARIANT: EncircleVariant = 'sauron'

// §28 (2026-05-13) — Broken-machine OVERLAYS. Each overlay sits on top of the
// base variant. Labels are used in tooltip composition + i18n fallback.
const OVERLAYS: Record<EncircleOverlay, { label: string }> = {
  glitch:  { label: 'Glitch' },
  cascade: { label: 'Cascade' },
  'panic-a': { label: 'Panic · CRT Meltdown' },
  'panic-b': { label: 'Panic · Kernel Panic' },
  'panic-c': { label: 'Panic · Reality Fracture' },
  // §pass43 (2026-05-18) — 8 new broken-machine overlays
  breach:   { label: 'Breach' },
  refract:  { label: 'Refract' },
  stutter:  { label: 'Stutter' },
  bleed:    { label: 'Bleed' },
  crackle:  { label: 'Crackle' },
  feedback: { label: 'Feedback' },
  spatter:  { label: 'Spatter' },
  unravel:  { label: 'Unravel' },
  // §pass67 (2026-05-23) — 8 new registry-themed broken-machine overlays
  redaction:    { label: 'Redaction' },
  manifold:     { label: 'Manifold' },
  rugpull:      { label: 'Tear-out' },
  shilling:     { label: 'Notifications' },
  brownout:     { label: 'Brownout' },
  stampede:     { label: 'Stampede' },
  'karma-debt': { label: 'Karma Debt' },
  freeze:       { label: 'Freeze' },
}

const visible = computed(() => {
  return Boolean(props.tier && (CONFIG as any)[props.tier])
})

// Resolve the effective variant — explicit prop > default.
// Trust the prop value if truthy. The VARIANTS-existence check was
// removed 2026-05-12: an edge case made 'glitch' fall through to the
// 'sauron' default even though VARIANTS['glitch'] existed (suspected
// minifier / property-access quirk). The CSS rules tolerate unknown
// variants by simply not matching, so a defensive sauron fallback
// hurt more than it helped.
const effectiveVariant = computed<EncircleVariant>(() => {
  const v = props.variant as EncircleVariant | null
  return (v || DEFAULT_VARIANT) as EncircleVariant
})

// §28 (2026-05-13) — Effective overlay (null = no overlay). Independent axis;
// the same prop pattern as effectiveVariant. NULL/empty/unknown all coalesce
// to null so the v-if blocks render nothing.
const effectiveOverlay = computed<EncircleOverlay | null>(() => {
  const o = props.overlay
  if (!o) return null
  return o as EncircleOverlay
})

// §15: render the Sauron SVG eye for shadow_chancellor + sauron, size sm
// and up. xs hides the SVG (avatar too small to be legible), the
// box-shadow frame breath carries the variant identity at xs.
const showSauronEye = computed(() => {
  return (
    visible.value
    && props.tier === 'shadow_chancellor'
    && effectiveVariant.value === 'sauron'
    && props.size !== 'xs'
  )
})

// §18: render the inline-SVG Halloween skull mask for shadow_chancellor +
// halloween. xs and sm hide the SVG (mask detail too small to read).
const showHalloweenMask = computed(() => {
  return (
    visible.value
    && props.tier === 'shadow_chancellor'
    && effectiveVariant.value === 'halloween'
    && !['xs', 'sm'].includes(props.size || 'md')
  )
})

// §19: render the inline-SVG Matrix katakana glyph rain for shadow_chancellor
// + matrix. Streams animate via CSS translateY (linear, infinite, offset
// phases per-stream so they don't sync). xs and sm hide (glyphs unreadable
// at <36px; frame styling carries the variant identity at small sizes).
const showMatrixRain = computed(() => {
  return (
    visible.value
    && props.tier === 'shadow_chancellor'
    && effectiveVariant.value === 'matrix'
    && !['xs', 'sm'].includes(props.size || 'md')
  )
})

// §28 (2026-05-13) — Broken-machine overlay gates. Now driven by
// `effectiveOverlay` (independent axis), not effectiveVariant. Size gate:
// xs hidden (avatar too small to read 5-px features); sm and up render.
// Commander 2026-05-15: agent cards use size="sm" — overlays MUST render.
const showGlitchOverlay = computed(() => {
  return (
    visible.value
    && effectiveOverlay.value === 'glitch'
    && props.size !== 'xs'
  )
})

const showCascadeOverlay = computed(() => {
  return (
    visible.value
    && effectiveOverlay.value === 'cascade'
    && props.size !== 'xs'
  )
})

// §29 (2026-05-13) — Panic tournament. Three design directions A/B/C.
const showPanicAOverlay = computed(() => {
  return (
    visible.value
    && effectiveOverlay.value === 'panic-a'
    && props.size !== 'xs'
  )
})

const showPanicBOverlay = computed(() => {
  return (
    visible.value
    && effectiveOverlay.value === 'panic-b'
    && props.size !== 'xs'
  )
})

const showPanicCOverlay = computed(() => {
  return (
    visible.value
    && effectiveOverlay.value === 'panic-c'
    && props.size !== 'xs'
  )
})

// §pass43 (2026-05-18) — 8 new broken-machine overlays. Same gate shape as
// glitch/cascade/panic-*: tier visible + overlay matches + size != xs.
const showBreachOverlay   = computed(() => visible.value && effectiveOverlay.value === 'breach'   && props.size !== 'xs')
const showRefractOverlay  = computed(() => visible.value && effectiveOverlay.value === 'refract'  && props.size !== 'xs')
const showStutterOverlay  = computed(() => visible.value && effectiveOverlay.value === 'stutter'  && props.size !== 'xs')
const showBleedOverlay    = computed(() => visible.value && effectiveOverlay.value === 'bleed'    && props.size !== 'xs')
const showCrackleOverlay  = computed(() => visible.value && effectiveOverlay.value === 'crackle'  && props.size !== 'xs')
const showFeedbackOverlay = computed(() => visible.value && effectiveOverlay.value === 'feedback' && props.size !== 'xs')
const showSpatterOverlay  = computed(() => visible.value && effectiveOverlay.value === 'spatter'  && props.size !== 'xs')
const showUnravelOverlay  = computed(() => visible.value && effectiveOverlay.value === 'unravel'  && props.size !== 'xs')

// §pass67 (2026-05-23) — 8 new registry-themed broken-machine overlays.
const showRedactionOverlay = computed(() => visible.value && effectiveOverlay.value === 'redaction' && props.size !== 'xs')
const showManifoldOverlay  = computed(() => visible.value && effectiveOverlay.value === 'manifold'  && props.size !== 'xs')
const showRugpullOverlay   = computed(() => visible.value && effectiveOverlay.value === 'rugpull'   && props.size !== 'xs')
const showShillingOverlay  = computed(() => visible.value && effectiveOverlay.value === 'shilling'  && props.size !== 'xs')
const showBrownoutOverlay  = computed(() => visible.value && effectiveOverlay.value === 'brownout'  && props.size !== 'xs')
const showStampedeOverlay  = computed(() => visible.value && effectiveOverlay.value === 'stampede'  && props.size !== 'xs')
const showKarmaDebtOverlay = computed(() => visible.value && effectiveOverlay.value === 'karma-debt' && props.size !== 'xs')
const showFreezeOverlay    = computed(() => visible.value && effectiveOverlay.value === 'freeze'    && props.size !== 'xs')

const tooltip = computed(() => {
  if (props.tooltipOverride) return props.tooltipOverride
  const t = props.tier as EncircleTier | null
  if (!t || !CONFIG[t]) return ''
  const variantLabel = VARIANTS[effectiveVariant.value]?.label ?? effectiveVariant.value
  const o = effectiveOverlay.value
  const overlayLabel = o ? OVERLAYS[o]?.label ?? o : null
  return overlayLabel
    ? `${CONFIG[t].label} backer · ${variantLabel} · ${overlayLabel}`
    : `${CONFIG[t].label} backer · ${variantLabel}`
})

// Image load failure → fall back to initials/icon.
const imgBroken = ref(false)
function onAvatarError() { imgBroken.value = true }
watch(() => props.avatarUrl, () => { imgBroken.value = false })
</script>

<style scoped>
/* ── §LEGACYFLARE (2026-09-09) — a host that has no headroom says so ──────────────────────
   His report: *"its agents avatars are displayed bugged but i dont know. never seens this
   kind of bug."* Nothing was broken: the Sauron eye is the ONE ornament in this component
   drawn OUTSIDE its own box (top: -45%…-70%, width up to 240%), deliberately, so it reads as
   "watching from above" over a header avatar with open space around it. Measured on
   Registry-A's public /explore: a 36px avatar, a 72x32 eye starting 22px ABOVE it, and no
   ancestor clipping it — in a card grid that is a dark smudge hanging off the card's top
   edge, and at that size the iris detail is not legible either. Giving the card 30px of
   headroom was tried first and did NOT fix it; the size is the problem, not the room.

   The component cannot know it is in a dense grid, so the HOST declares it: any ancestor
   carrying `.fc-dense` gets the ring, the frame breath and the palette, and no ornament that
   would paint outside the avatar. One rule, in the component that owns the behaviour, usable
   by every future dense surface — rather than a per-view selector that the next grid forgets.
   Scoped CSS only scopes the RIGHTMOST selector, so `.fc-dense` matches an ancestor outside
   this component by design.

   ⚠ Deliberately narrow: `.fc-sauron-eye` is the only ornament with a negative `top` in this
   file (verified by scanning every rule), so it is the only one that can escape its box. If a
   future variant is drawn outside the box, it belongs on this list too. */
.fc-dense .fc-sauron-eye { display: none; }

/* ════════════════════════════════════════════════════════════════════
   BASE — sizing + frame + fallback (variant-agnostic)
   ════════════════════════════════════════════════════════════════════
   Every variant inherits the base sizing + frame structure. Halos and
   palette overrides live in the per-variant blocks below. */

.fc-encircle {
  display: inline-block;
  position: relative;
  flex-shrink: 0;
  vertical-align: middle;
  user-select: none;
  isolation: isolate;
}
.fc-encircle-size-xs { width: 22px; height: 22px; }
.fc-encircle-size-sm { width: 26px; height: 26px; }
.fc-encircle-size-md { width: 36px; height: 36px; }
.fc-encircle-size-lg { width: 48px; height: 48px; }
.fc-encircle-size-xl { width: 96px; height: 96px; }

/* Inner frame — sits ABOVE both halo layers (z 3).
   §15: extended transition list lets the FRAME box-shadow cross-fade smoothly
   between variants when the same shadow-layer count is used (sauron + goth +
   obsidian all share 4-layer signatures). Variants with different counts
   (void has 7) snap discretely — CSS box-shadow only interpolates same-count.
   The 600ms duration is intentional: long enough to read as a transition,
   short enough that the user perceives the switch as immediate. */
.fc-encircle-frame {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  overflow: hidden;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 1);
  transition:
    box-shadow 600ms cubic-bezier(.4,.0,.2,1),
    background 400ms ease;
}
/* Halo layers — opacity transitions even when background-image gradients
   don't (CSS doesn't interpolate gradient image content; we get a soft
   fade by transitioning opacity, even though the gradient swap is
   technically discrete). */
.fc-encircle-shadow_chancellor::before,
.fc-encircle-shadow_chancellor::after {
  transition: opacity 400ms ease, filter 400ms ease;
}
.fc-encircle-avatar-fallback {
  transition: background 400ms ease, color 400ms ease;
}
.fc-encircle-avatar-img {
  width: 100%; height: 100%; object-fit: cover; display: block;
}
/* §MARKCOLLAR — the earned mark's layer inside the frame. z 4 is the tie value
   it shares with the last variant art and the first registry-themed overlays;
   DOM order (see the template block) resolves both ties correctly. Deep because
   the child component is scoped. */
.fc-earned-collar { z-index: 4; }
:deep(.fc-earned-collar) { z-index: 4; }
.fc-encircle-avatar-fallback {
  width: 100%; height: 100%;
  display: flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', 'Fira Code', ui-monospace, monospace;
  font-weight: 700;
  letter-spacing: 0.04em;
}
.fc-encircle-initials { font-size: 0.42em; line-height: 1; }
.fc-encircle-size-xs .fc-encircle-initials { font-size: 9px; }
.fc-encircle-size-sm .fc-encircle-initials { font-size: 11px; }
.fc-encircle-size-md .fc-encircle-initials { font-size: 14px; }
.fc-encircle-size-lg .fc-encircle-initials { font-size: 18px; }
.fc-encircle-size-xl .fc-encircle-initials { font-size: 36px; }
.fc-encircle-icon { width: 50%; height: 50%; opacity: 0.85; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 1 — SAURON (default, §15 AAA+ refinement)
   ════════════════════════════════════════════════════════════════════
   Pure black ring + SVG eye watching from above the avatar. The SVG
   carries the "Eye of Sauron" identity (cat-pupil iris + flame aura
   + rising embers + 7s blink). The ring frame breathes red. */

.fc-encircle-shadow_chancellor.fc-encircle-sauron .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.92),
    0 0 0 1.5px rgba(127, 29, 29, 0.65),
    0 0 0 2.5px rgba(0, 0, 0, 1),
    0 -10px 28px -4px rgba(220, 38, 38, 0.55);  /* upward red glow */
  animation: fc-sauron-breath 4.2s cubic-bezier(.4,.0,.2,1) infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-sauron:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.92),
    0 0 0 2px rgba(252, 165, 165, 1),
    0 0 0 3px rgba(0, 0, 0, 1),
    0 -14px 36px -4px rgba(220, 38, 38, 0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-sauron .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 100% 65% at 50% 110%,
      rgba(127, 29, 29, 0.30) 0%, transparent 65%),
    linear-gradient(180deg, rgba(20, 14, 18, 1) 0%, rgba(0, 0, 0, 1) 100%);
  color: rgba(254, 215, 170, 0.95);
  text-shadow: 0 0 8px rgba(220, 38, 38, 0.55);
}

/* The SVG-based Sauron eye container — sits above the encirclement bbox,
   visible only at md/lg/xl. The SVG itself uses overflow:visible so the
   flame aura extends slightly beyond the container bounds (which is what
   sells the "burning" feel). */
.fc-sauron-eye {
  position: absolute;
  left: 50%;
  pointer-events: none;
  z-index: 2;
  filter: drop-shadow(0 0 14px rgba(220, 38, 38, 0.55));
}
.fc-sauron-eye svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

/* Per-size positioning of the eye. The 140x90 viewBox + xMidYMid meet
   gives a 14:9 almond canvas. Container scales aggressively at smaller
   sizes so the eye stays legible — at md (header avatar), the eye is
   ~80% of the avatar size hovering above. */
.fc-encircle-size-sm .fc-sauron-eye {
  /* §19 (2026-05-13): bumped width 220%→240% + height 95%→108% so the
     eye reads at AgentSwitcher dropdown row sizes (26px avatar). The
     SVG viewBox aspect is 14:9 — at sm sizes preserveAspectRatio="meet"
     was leaving the eye visually small inside the container. */
  top: -70%;
  width: 240%;
  height: 108%;
  transform: translateX(-50%);
}
.fc-encircle-size-md .fc-sauron-eye {
  top: -60%;
  width: 200%;
  height: 90%;
  transform: translateX(-50%);
}
.fc-encircle-size-lg .fc-sauron-eye {
  top: -55%;
  width: 180%;
  height: 82%;
  transform: translateX(-50%);
}
.fc-encircle-size-xl .fc-sauron-eye {
  top: -45%;
  width: 170%;
  height: 72%;
  transform: translateX(-50%);
}

/* SVG sub-element animations. transform-origin matches viewBox coords
   (70, 48) — center of the eye in 140×90 viewBox. */
.fc-sauron-flame {
  transform-origin: 70px 48px;
  animation: fc-sauron-flicker 0.9s ease-in-out infinite;
}
.fc-sauron-flame-core {
  transform-origin: 70px 48px;
  animation: fc-sauron-flicker-fast 0.5s ease-in-out infinite;
}
.fc-sauron-eyelid {
  transform-origin: 70px 48px;
  animation: fc-sauron-blink 7s ease-in-out infinite;
}
.fc-sauron-ember {
  transform-origin: center;
  opacity: 0;
}
.fc-sauron-ember-1 { animation: fc-sauron-ember 3.2s ease-in 0.0s infinite; }
.fc-sauron-ember-2 { animation: fc-sauron-ember 4.1s ease-in 0.8s infinite; }
.fc-sauron-ember-3 { animation: fc-sauron-ember 3.6s ease-in 1.6s infinite; }
.fc-sauron-ember-4 { animation: fc-sauron-ember 4.8s ease-in 0.4s infinite; }
.fc-sauron-ember-5 { animation: fc-sauron-ember 3.0s ease-in 2.2s infinite; }

@keyframes fc-sauron-breath {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.92),
      0 0 0 1.5px rgba(127, 29, 29, 0.65),
      0 0 0 2.5px rgba(0, 0, 0, 1),
      0 -10px 28px -4px rgba(220, 38, 38, 0.55);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.92),
      0 0 0 2px rgba(220, 38, 38, 0.85),
      0 0 0 3px rgba(0, 0, 0, 1),
      0 -16px 38px -4px rgba(252, 165, 165, 0.78);
  }
}
@keyframes fc-sauron-flicker {
  0%, 100% { opacity: 1;    transform: scale(1)     translateY(0); }
  28%      { opacity: 0.93; transform: scale(1.02)  translateY(-0.4px); }
  55%      { opacity: 0.97; transform: scale(0.99)  translateY(0.3px); }
  78%      { opacity: 0.95; transform: scale(1.01)  translateY(-0.2px); }
}
@keyframes fc-sauron-flicker-fast {
  0%, 100% { opacity: 0.6;  transform: scale(1); }
  40%      { opacity: 0.85; transform: scale(1.06); }
  72%      { opacity: 0.7;  transform: scale(0.97); }
}
@keyframes fc-sauron-blink {
  0%, 91%, 100% { transform: scaleY(1); }
  93%           { transform: scaleY(0.18); }
  95%           { transform: scaleY(0.05); }
  97%           { transform: scaleY(0.4); }
}
@keyframes fc-sauron-ember {
  0%   { transform: translate(0, 0)    scale(1);   opacity: 0; }
  10%  {                                              opacity: 0.85; }
  60%  {                                              opacity: 0.55; }
  100% { transform: translate(2px, -28px) scale(0.35); opacity: 0; }
}

/* xs only: no SVG eye (too small to read). sm+ renders the eye because
   showSauronEye computed gates on size !== 'xs'. The frame's red
   breathing carries the variant identity at xs. */
.fc-encircle-size-xs .fc-sauron-eye { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 2 — GOTH (§15 AAA+ refinement)
   ════════════════════════════════════════════════════════════════════
   Wet, viscous, organic. Each compass-point blob has its own hue
   (deepest indigo north, magenta east, biggest indigo south, violet
   west). Heavier blur for true gooeyness. Meniscus highlights suggest
   wet surface tension. Inner rotators keep the 35s counter-rotate. */

.fc-encircle-shadow_chancellor.fc-encircle-goth .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.45),
    0 0 0 1.5px rgba(167, 139, 250, 0.88),
    0 0 0 2.5px rgba(15, 5, 25, 0.95),
    0 0 14px 2px rgba(91, 33, 158, 0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-goth:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.45),
    0 0 0 1.5px rgba(216, 200, 255, 1),
    0 0 0 2.5px rgba(15, 5, 25, 0.95),
    0 0 22px 3px rgba(91, 33, 158, 0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-goth .fc-encircle-avatar-fallback {
  background:
    radial-gradient(circle at 35% 28%, rgba(120, 60, 200, 0.55) 0%, transparent 55%),
    radial-gradient(circle at 70% 76%, rgba(66, 20, 130, 0.55) 0%, transparent 60%),
    linear-gradient(160deg, rgba(38, 14, 70, 1) 0%, rgba(12, 4, 24, 1) 100%);
  color: #e9d5ff;
  text-shadow: 0 0 7px rgba(167, 139, 250, 0.65);
}

/* Outer wet blobs — each compass point gets its own hue for visual depth.
   Heavier blur (1.6px) for the goo. */
.fc-encircle-shadow_chancellor.fc-encircle-goth::before {
  content: '';
  position: absolute;
  inset: -28%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* North — deepest indigo */
    radial-gradient(ellipse 24% 16% at 50% 4%,
      rgba(12, 4, 32, 0.97) 0%,
      rgba(33, 8, 68, 0.85) 30%,
      rgba(56, 18, 110, 0.5) 55%,
      transparent 80%),
    /* East — magenta-tinted */
    radial-gradient(ellipse 19% 13% at 96% 42%,
      rgba(40, 8, 50, 0.94) 0%,
      rgba(78, 14, 82, 0.78) 30%,
      rgba(140, 38, 130, 0.42) 58%,
      transparent 82%),
    /* South — biggest, indigo */
    radial-gradient(ellipse 26% 17% at 56% 96%,
      rgba(10, 5, 38, 0.96) 0%,
      rgba(28, 10, 90, 0.85) 32%,
      rgba(50, 25, 130, 0.5) 56%,
      transparent 80%),
    /* West — violet */
    radial-gradient(ellipse 20% 14% at 4% 70%,
      rgba(22, 8, 52, 0.93) 0%,
      rgba(56, 22, 130, 0.78) 32%,
      rgba(110, 70, 220, 0.4) 58%,
      transparent 82%);
  filter: blur(1.6px) saturate(1.35);
  -webkit-mask: radial-gradient(circle, transparent 38%, black 49%);
          mask: radial-gradient(circle, transparent 38%, black 49%);
  animation: fc-goth-rotate 26s linear infinite;
}

/* Inner highlights + meniscus tension dots — counter-rotating */
.fc-encircle-shadow_chancellor.fc-encircle-goth::after {
  content: '';
  position: absolute;
  inset: -12%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Meniscus highlights (wet surface tension) — §18 polish: brighter
       white-cores so they actually pop as glints on the gooey blobs. */
    radial-gradient(ellipse 4.5% 3.5% at 50% 6%,
      rgba(255, 255, 255, 0.85) 0%, rgba(232, 213, 255, 0.5) 35%, transparent 75%),
    radial-gradient(ellipse 4% 3.2% at 92% 44%,
      rgba(255, 240, 255, 0.78) 0%, rgba(255, 200, 240, 0.45) 35%, transparent 75%),
    radial-gradient(ellipse 4.5% 3.5% at 56% 94%,
      rgba(255, 255, 255, 0.78) 0%, rgba(220, 200, 255, 0.45) 35%, transparent 75%),
    radial-gradient(ellipse 4% 3.2% at 8% 70%,
      rgba(255, 240, 255, 0.78) 0%, rgba(200, 180, 255, 0.45) 35%, transparent 75%),
    /* Inner halo blobs — §18 polish: brighter violet/magenta cycle */
    radial-gradient(ellipse 13% 10% at 78% 14%,
      rgba(196, 181, 253, 0.78) 0%, transparent 72%),
    radial-gradient(ellipse 14% 11% at 90% 76%,
      rgba(232, 140, 240, 0.72) 0%, transparent 74%),
    radial-gradient(ellipse 13% 10% at 22% 92%,
      rgba(167, 200, 255, 0.72) 0%, transparent 72%),
    radial-gradient(ellipse 14% 11% at 8% 26%,
      rgba(216, 200, 255, 0.78) 0%, transparent 74%);
  filter: blur(0.6px) saturate(1.15);
  -webkit-mask: radial-gradient(circle, transparent 42%, black 55%);
          mask: radial-gradient(circle, transparent 42%, black 55%);
  animation: fc-goth-counter-rotate 35s linear infinite;
}

@keyframes fc-goth-rotate         { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes fc-goth-counter-rotate { from { transform: rotate(0deg); } to { transform: rotate(-360deg); } }

.fc-encircle-size-xs.fc-encircle-goth::before,
.fc-encircle-size-xs.fc-encircle-goth::after { display: none; }
.fc-encircle-size-sm.fc-encircle-goth::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 3 — OBSIDIAN (§15 AAA+ refinement)
   ════════════════════════════════════════════════════════════════════
   Polished black stone with 8 sharp prismatic facet bands at 45°
   intervals (replaces soft conic). Static fresnel rim highlight on
   the frame (replaces sheen sweep). Slow 60s rotation. Crisp.
*/

.fc-encircle-shadow_chancellor.fc-encircle-obsidian .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 1),
    /* Top fresnel highlight — bright sliver suggesting overhead light */
    inset 0 6px 16px -8px rgba(220, 240, 255, 0.7),
    /* Outer steel bezel */
    0 0 0 1.5px rgba(190, 200, 215, 0.92),
    0 0 0 2.5px rgba(8, 12, 20, 1),
    0 0 14px 1px rgba(150, 180, 220, 0.28);
}
.fc-encircle-shadow_chancellor.fc-encircle-obsidian:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 1),
    inset 0 8px 18px -8px rgba(240, 248, 255, 0.85),
    0 0 0 2px rgba(220, 230, 245, 1),
    0 0 0 3px rgba(8, 12, 20, 1),
    0 0 22px 2px rgba(150, 180, 220, 0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-obsidian .fc-encircle-avatar-fallback {
  background:
    /* Crisp diagonal facet break */
    linear-gradient(135deg,
      rgba(70, 84, 108, 0.55) 0%,
      rgba(22, 28, 38, 1) 22%,
      rgba(4, 6, 10, 1) 48%,
      rgba(0, 0, 0, 1) 52%,
      rgba(18, 22, 30, 1) 78%,
      rgba(70, 84, 108, 0.4) 100%),
    /* Secondary 45° facet sliver */
    linear-gradient(45deg,
      transparent 47%, rgba(120, 140, 170, 0.22) 50%, transparent 53%);
  color: rgba(210, 222, 240, 0.95);
  text-shadow: 0 0 8px rgba(170, 210, 235, 0.55);
}

/* 8 sharp prismatic facet bands evenly distributed at 45° intervals.
   Each facet is a thin peak with brighter+wider color now (the prior
   pass had them too subtle). Colors cycle cyan → violet → green → gold. */
.fc-encircle-shadow_chancellor.fc-encircle-obsidian::before {
  content: '';
  position: absolute;
  inset: -22%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    /* Facet 1 @ 22.5° — cyan, wider band w/ halo */
    transparent 14deg,
    rgba(120, 200, 220, 0.55) 18deg,
    rgba(220, 240, 250, 1) 22.5deg,
    rgba(120, 200, 220, 0.55) 27deg,
    transparent 31deg,
    /* Facet 2 @ 67.5° — violet */
    transparent 59deg,
    rgba(180, 100, 220, 0.55) 63deg,
    rgba(230, 200, 250, 1) 67.5deg,
    rgba(180, 100, 220, 0.55) 72deg,
    transparent 76deg,
    /* Facet 3 @ 112.5° — green */
    transparent 104deg,
    rgba(70, 220, 180, 0.55) 108deg,
    rgba(180, 250, 230, 1) 112.5deg,
    rgba(70, 220, 180, 0.55) 117deg,
    transparent 121deg,
    /* Facet 4 @ 157.5° — gold */
    transparent 149deg,
    rgba(220, 180, 100, 0.55) 153deg,
    rgba(250, 230, 180, 1) 157.5deg,
    rgba(220, 180, 100, 0.55) 162deg,
    transparent 166deg,
    /* Facet 5 @ 202.5° — cyan */
    transparent 194deg,
    rgba(120, 200, 220, 0.50) 198deg,
    rgba(220, 240, 250, 0.92) 202.5deg,
    rgba(120, 200, 220, 0.50) 207deg,
    transparent 211deg,
    /* Facet 6 @ 247.5° — violet */
    transparent 239deg,
    rgba(180, 100, 220, 0.50) 243deg,
    rgba(230, 200, 250, 0.92) 247.5deg,
    rgba(180, 100, 220, 0.50) 252deg,
    transparent 256deg,
    /* Facet 7 @ 292.5° — green */
    transparent 284deg,
    rgba(70, 220, 180, 0.50) 288deg,
    rgba(180, 250, 230, 0.92) 292.5deg,
    rgba(70, 220, 180, 0.50) 297deg,
    transparent 301deg,
    /* Facet 8 @ 337.5° — gold */
    transparent 329deg,
    rgba(220, 180, 100, 0.50) 333deg,
    rgba(250, 230, 180, 0.92) 337.5deg,
    rgba(220, 180, 100, 0.50) 342deg,
    transparent 346deg,
    transparent 360deg
  );
  filter: blur(0.5px);
  -webkit-mask: radial-gradient(circle, transparent 41%, black 49%, transparent 64%);
          mask: radial-gradient(circle, transparent 41%, black 49%, transparent 64%);
  opacity: 1;
  animation: fc-obsidian-shift 60s linear infinite;
}

/* Static fresnel rim highlight — bright top, softer bottom. Replaces
   the sheen sweep entirely. Obsidian's aesthetic is "still + polished". */
.fc-encircle-shadow_chancellor.fc-encircle-obsidian::after {
  content: '';
  position: absolute;
  inset: -6%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Bright top fresnel */
    radial-gradient(ellipse 90% 28% at 50% 6%,
      rgba(220, 240, 255, 0.6) 0%,
      rgba(180, 210, 240, 0.28) 30%,
      transparent 60%),
    /* Soft bottom counter-light */
    radial-gradient(ellipse 70% 24% at 50% 100%,
      rgba(140, 170, 200, 0.32) 0%,
      transparent 55%);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 48%, black 51%, transparent 54%);
          mask: radial-gradient(circle, transparent 44%, black 48%, black 51%, transparent 54%);
  mix-blend-mode: screen;
}

@keyframes fc-obsidian-shift {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.fc-encircle-size-xs.fc-encircle-obsidian::before,
.fc-encircle-size-xs.fc-encircle-obsidian::after,
.fc-encircle-size-sm.fc-encircle-obsidian::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 4 — VOID (§15 AAA+ refinement)
   ════════════════════════════════════════════════════════════════════
   Black hole with accretion disk. 7 concentric event-horizon bands
   replace the prior 2-band setup. Asymmetric photon-ring highlight at
   11 o'clock + dimmer mirror at bottom-right (gravitational lensing
   artifact à la Interstellar). Slight ellipse-scale to suggest lensing.
   Pure jet-black core.
*/

.fc-encircle-shadow_chancellor.fc-encircle-void .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    /* Innermost bright ring — pale violet */
    0 0 0 1.5px rgba(196, 181, 253, 0.65),
    /* gap */
    0 0 0 3.5px rgba(0, 0, 0, 1),
    /* Mid ring — red-shift */
    0 0 0 5px rgba(127, 29, 29, 0.55),
    /* gap */
    0 0 0 6.5px rgba(0, 0, 0, 1),
    /* Outer ring — deeper red */
    0 0 0 8px rgba(127, 29, 29, 0.32),
    0 0 18px 2px rgba(127, 29, 29, 0.4);
  animation: fc-void-pulse 4.6s cubic-bezier(.4,.0,.2,1) infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-void:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    0 0 0 2px rgba(216, 200, 255, 0.85),
    0 0 0 4px rgba(0, 0, 0, 1),
    0 0 0 6px rgba(220, 38, 38, 0.7),
    0 0 0 8px rgba(0, 0, 0, 1),
    0 0 0 10px rgba(127, 29, 29, 0.55),
    0 0 28px 3px rgba(254, 215, 170, 0.65);
}
.fc-encircle-shadow_chancellor.fc-encircle-void .fc-encircle-avatar-fallback {
  /* Pure jet black with warm rim glow */
  background:
    radial-gradient(circle at 50% 50%,
      #000 0%,
      #000 55%,
      rgba(20, 0, 8, 1) 85%,
      rgba(40, 10, 28, 1) 100%);
  color: rgba(254, 215, 170, 0.92);
  text-shadow:
    0 0 7px rgba(254, 215, 170, 0.48),
    0 0 14px rgba(127, 29, 29, 0.55);
}

/* 7 concentric event-horizon bands. Each is a thin radial gradient with
   a peak at the band radius and quick falloff. Slight ellipse-scale
   suggests gravitational lensing distortion. */
.fc-encircle-shadow_chancellor.fc-encircle-void::before {
  content: '';
  position: absolute;
  inset: -32%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    radial-gradient(circle, transparent 30%, rgba(167, 139, 250, 0.10) 31.5%, transparent 33%),
    radial-gradient(circle, transparent 34%, rgba(127, 29, 29, 0.18) 35.5%, transparent 37%),
    radial-gradient(circle, transparent 38%, rgba(196, 70, 70, 0.32) 39.5%, transparent 41%),
    radial-gradient(circle, transparent 42%, rgba(167, 139, 250, 0.45) 43.5%, transparent 45%),
    radial-gradient(circle, transparent 46%, rgba(220, 38, 38, 0.55) 47.5%, transparent 49.5%),
    radial-gradient(circle, transparent 50.5%, rgba(196, 181, 253, 0.65) 52%, transparent 54%),
    radial-gradient(circle, transparent 55%, rgba(167, 139, 250, 0.28) 56.5%, transparent 58%);
  filter: blur(0.3px);
  /* Slight horizontal stretch = gravitational lensing */
  transform: scaleX(1.045);
  animation: fc-void-disk 12s ease-in-out infinite;
}

/* Asymmetric photon ring — Interstellar reference. Bright warm highlight
   at top-left, dimmer crimson mirror at bottom-right. Masked to the
   accretion-disk band radii only. */
.fc-encircle-shadow_chancellor.fc-encircle-void::after {
  content: '';
  position: absolute;
  inset: -20%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Bright photon arc top-left (10-11 o'clock) */
    radial-gradient(ellipse 30% 24% at 22% 18%,
      rgba(254, 215, 170, 0.78) 0%,
      rgba(252, 165, 165, 0.55) 25%,
      rgba(220, 80, 80, 0.30) 50%,
      transparent 68%),
    /* Lensing-mirror artifact bottom-right (4-5 o'clock) */
    radial-gradient(ellipse 22% 18% at 78% 82%,
      rgba(220, 38, 38, 0.45) 0%,
      rgba(127, 29, 29, 0.25) 35%,
      transparent 62%),
    /* Thin accretion-disk highlight ring */
    radial-gradient(circle, transparent 48%,
      rgba(254, 215, 170, 0.40) 49.5%,
      transparent 51.5%);
  filter: blur(0.5px);
  -webkit-mask: radial-gradient(circle, transparent 38%, black 47%, black 58%, transparent 62%);
          mask: radial-gradient(circle, transparent 38%, black 47%, black 58%, transparent 62%);
  animation: fc-void-disk-inner 4.6s cubic-bezier(.4,.0,.2,1) infinite;
}

@keyframes fc-void-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      0 0 0 1.5px rgba(196, 181, 253, 0.65),
      0 0 0 3.5px rgba(0, 0, 0, 1),
      0 0 0 5px rgba(127, 29, 29, 0.55),
      0 0 0 6.5px rgba(0, 0, 0, 1),
      0 0 0 8px rgba(127, 29, 29, 0.32),
      0 0 18px 2px rgba(127, 29, 29, 0.4);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      0 0 0 1.5px rgba(216, 200, 255, 0.9),
      0 0 0 3.5px rgba(0, 0, 0, 1),
      0 0 0 5px rgba(220, 38, 38, 0.78),
      0 0 0 6.5px rgba(0, 0, 0, 1),
      0 0 0 8px rgba(127, 29, 29, 0.55),
      0 0 26px 3px rgba(254, 215, 170, 0.55);
  }
}
@keyframes fc-void-disk {
  0%, 100% { opacity: 0.7; transform: scaleX(1.045) scale(1); }
  50%      { opacity: 1;   transform: scaleX(1.06)  scale(1.03); }
}
@keyframes fc-void-disk-inner {
  0%, 100% { opacity: 0.55; transform: scale(0.98); }
  50%      { opacity: 0.95; transform: scale(1.02); }
}

.fc-encircle-size-xs.fc-encircle-void::before,
.fc-encircle-size-xs.fc-encircle-void::after,
.fc-encircle-size-sm.fc-encircle-void::before { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 5 — AURORA (§15.3 new variant)
   ════════════════════════════════════════════════════════════════════
   Cold ethereal northern-lights curtains. Vertical ribbons of green,
   cyan, and violet flowing horizontally. Calm, otherworldly — the
   counterpart to Sauron's hot menace.
*/

.fc-encircle-shadow_chancellor.fc-encircle-aurora .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 8, 16, 0.95),
    0 0 0 1.5px rgba(74, 222, 128, 0.65),
    0 0 0 2.5px rgba(2, 10, 22, 1),
    0 -8px 22px -2px rgba(34, 197, 250, 0.55);
  animation: fc-aurora-breath 5.4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-aurora:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 8, 16, 0.95),
    0 0 0 2px rgba(167, 243, 208, 1),
    0 0 0 3px rgba(2, 10, 22, 1),
    0 -14px 30px -2px rgba(34, 197, 250, 0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-aurora .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 80% 50% at 30% 20%, rgba(74, 222, 128, 0.28) 0%, transparent 60%),
    radial-gradient(ellipse 70% 50% at 75% 80%, rgba(167, 139, 250, 0.32) 0%, transparent 60%),
    linear-gradient(180deg, rgba(8, 16, 32, 1) 0%, rgba(2, 8, 18, 1) 100%);
  color: rgba(209, 250, 229, 0.95);
  text-shadow: 0 0 8px rgba(74, 222, 128, 0.55);
}

/* Outer curtain ribbons — 4 vertical streaks at different x positions
   with green / cyan / violet color stops. Translates horizontally to
   sell the flowing-curtain feel. Heavy blur for ethereal softness.
   §18 polish: saturated to 1.65, brighter green + violet peaks. */
.fc-encircle-shadow_chancellor.fc-encircle-aurora::before {
  content: '';
  position: absolute;
  inset: -28%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Green curtain (left-of-center) — brightest green peak */
    radial-gradient(ellipse 12% 65% at 30% 50%,
      rgba(110, 255, 158, 0.85) 0%,
      rgba(74, 222, 128, 0.6) 30%,
      rgba(34, 197, 94, 0.32) 55%,
      transparent 78%),
    /* Cyan curtain — full ice-cyan */
    radial-gradient(ellipse 10% 60% at 50% 45%,
      rgba(125, 235, 255, 0.9) 0%,
      rgba(34, 211, 238, 0.6) 30%,
      rgba(56, 189, 248, 0.32) 55%,
      transparent 78%),
    /* Violet curtain (right) — saturated electric purple */
    radial-gradient(ellipse 12% 65% at 70% 50%,
      rgba(216, 180, 255, 0.85) 0%,
      rgba(167, 139, 250, 0.62) 30%,
      rgba(139, 92, 246, 0.32) 55%,
      transparent 78%),
    /* Hot pink edge — adds the magenta finger Commander asked for */
    radial-gradient(ellipse 10% 55% at 88% 55%,
      rgba(252, 165, 200, 0.7) 0%,
      rgba(244, 114, 182, 0.45) 35%, transparent 72%);
  filter: blur(2.2px) saturate(1.65);
  -webkit-mask: radial-gradient(circle, transparent 40%, black 48%, transparent 64%);
          mask: radial-gradient(circle, transparent 40%, black 48%, transparent 64%);
  animation: fc-aurora-flow 22s ease-in-out infinite alternate;
}

/* Inner secondary curtains — counter-drift for layered depth */
.fc-encircle-shadow_chancellor.fc-encircle-aurora::after {
  content: '';
  position: absolute;
  inset: -14%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 8% 40% at 22% 50%,
      rgba(125, 252, 175, 0.45) 0%, transparent 70%),
    radial-gradient(ellipse 7% 38% at 58% 45%,
      rgba(125, 211, 252, 0.5) 0%, transparent 70%),
    radial-gradient(ellipse 8% 40% at 82% 52%,
      rgba(196, 181, 253, 0.45) 0%, transparent 70%);
  filter: blur(1.4px);
  -webkit-mask: radial-gradient(circle, transparent 43%, black 52%, transparent 62%);
          mask: radial-gradient(circle, transparent 43%, black 52%, transparent 62%);
  animation: fc-aurora-flow-inner 14s ease-in-out infinite alternate;
}

@keyframes fc-aurora-breath {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 8, 16, 0.95),
      0 0 0 1.5px rgba(74, 222, 128, 0.65),
      0 0 0 2.5px rgba(2, 10, 22, 1),
      0 -8px 22px -2px rgba(34, 197, 250, 0.55);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 8, 16, 0.95),
      0 0 0 2px rgba(167, 243, 208, 0.95),
      0 0 0 3px rgba(2, 10, 22, 1),
      0 -14px 32px -2px rgba(34, 197, 250, 0.85);
  }
}
@keyframes fc-aurora-flow {
  from { transform: translateX(-6%); }
  to   { transform: translateX(6%); }
}
@keyframes fc-aurora-flow-inner {
  from { transform: translateX(4%); }
  to   { transform: translateX(-4%); }
}

.fc-encircle-size-xs.fc-encircle-aurora::before,
.fc-encircle-size-xs.fc-encircle-aurora::after,
.fc-encircle-size-sm.fc-encircle-aurora::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 6 — PHOENIX (§15.3 new variant)
   ════════════════════════════════════════════════════════════════════
   Rising fire bird wreath. Two flame "wings" arc upward and outward
   from the avatar. Hot orange/yellow with crimson accents, slightly
   more saturated than Sauron. Animated pulse + ember rise.
*/

.fc-encircle-shadow_chancellor.fc-encircle-phoenix .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(34, 8, 0, 0.95),
    0 0 0 1.5px rgba(251, 146, 60, 0.85),
    0 0 0 2.5px rgba(34, 8, 0, 1),
    0 -8px 26px -3px rgba(252, 165, 165, 0.6),
    0 0 18px 2px rgba(220, 38, 38, 0.45);
  animation: fc-phoenix-pulse 3.8s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-phoenix:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(34, 8, 0, 0.95),
    0 0 0 2px rgba(254, 215, 170, 1),
    0 0 0 3px rgba(34, 8, 0, 1),
    0 -14px 34px -3px rgba(254, 215, 170, 0.9),
    0 0 28px 3px rgba(220, 38, 38, 0.7);
}
.fc-encircle-shadow_chancellor.fc-encircle-phoenix .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 90% 70% at 50% 110%,
      rgba(252, 165, 165, 0.3) 0%, transparent 60%),
    radial-gradient(ellipse 80% 60% at 50% -5%,
      rgba(254, 215, 170, 0.32) 0%, transparent 65%),
    linear-gradient(180deg, rgba(40, 12, 4, 1) 0%, rgba(15, 4, 0, 1) 100%);
  color: rgba(254, 215, 170, 0.98);
  text-shadow: 0 0 10px rgba(251, 146, 60, 0.7);
}

/* Two "wings" — radial-gradient flames at left and right, extending
   upward and outward. Plus a tail flame at bottom. Sells the bird
   shape via positioned hotspots.
   §18 polish: brighter saturation, larger wing ellipses, hot-white
   center cores for the eye-popping fire-bird look. */
.fc-encircle-shadow_chancellor.fc-encircle-phoenix::before {
  content: '';
  position: absolute;
  inset: -32%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* LEFT WING — broad flame extending up-left, brighter core */
    radial-gradient(ellipse 36% 32% at 15% 28%,
      rgba(255, 251, 235, 0.95) 0%,
      rgba(252, 211, 77, 0.85) 18%,
      rgba(251, 146, 60, 0.65) 42%,
      rgba(220, 38, 38, 0.38) 68%,
      transparent 92%),
    /* RIGHT WING — mirror */
    radial-gradient(ellipse 36% 32% at 85% 28%,
      rgba(255, 251, 235, 0.95) 0%,
      rgba(252, 211, 77, 0.85) 18%,
      rgba(251, 146, 60, 0.65) 42%,
      rgba(220, 38, 38, 0.38) 68%,
      transparent 92%),
    /* TOP CREST — central highlight (head) */
    radial-gradient(ellipse 24% 20% at 50% 6%,
      rgba(255, 251, 235, 0.92) 0%,
      rgba(254, 215, 170, 0.65) 32%,
      transparent 72%),
    /* TAIL — bottom flame extending down, more crimson */
    radial-gradient(ellipse 26% 24% at 50% 92%,
      rgba(254, 215, 170, 0.78) 0%,
      rgba(220, 38, 38, 0.55) 38%,
      transparent 80%);
  filter: blur(1.1px) saturate(1.5);
  -webkit-mask: radial-gradient(circle, transparent 38%, black 49%);
          mask: radial-gradient(circle, transparent 38%, black 49%);
  animation: fc-phoenix-flicker 1.4s ease-in-out infinite alternate;
}

/* Ember sparks — 6 small radial dots around the rim that twinkle */
.fc-encircle-shadow_chancellor.fc-encircle-phoenix::after {
  content: '';
  position: absolute;
  inset: -16%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 2.5% 2.5% at 22% 18%,
      rgba(252, 211, 77, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 3% 3% at 78% 22%,
      rgba(251, 146, 60, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.2% 2.2% at 90% 50%,
      rgba(254, 215, 170, 0.92) 0%, transparent 65%),
    radial-gradient(ellipse 2.6% 2.6% at 76% 82%,
      rgba(252, 165, 165, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.4% 2.4% at 24% 80%,
      rgba(252, 211, 77, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.8% 2.8% at 10% 48%,
      rgba(251, 146, 60, 0.95) 0%, transparent 65%);
  filter: blur(0.5px);
  animation: fc-phoenix-sparks 1.9s ease-in-out infinite;
}

@keyframes fc-phoenix-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(34, 8, 0, 0.95),
      0 0 0 1.5px rgba(251, 146, 60, 0.85),
      0 0 0 2.5px rgba(34, 8, 0, 1),
      0 -8px 26px -3px rgba(252, 165, 165, 0.6),
      0 0 18px 2px rgba(220, 38, 38, 0.45);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(34, 8, 0, 0.95),
      0 0 0 2px rgba(254, 215, 170, 0.98),
      0 0 0 3px rgba(34, 8, 0, 1),
      0 -16px 36px -3px rgba(254, 215, 170, 0.92),
      0 0 28px 3px rgba(220, 38, 38, 0.7);
  }
}
@keyframes fc-phoenix-flicker {
  0%   { opacity: 0.95; transform: scale(1)    rotate(-1deg); }
  50%  { opacity: 1;    transform: scale(1.03) rotate(0deg); }
  100% { opacity: 0.97; transform: scale(1.01) rotate(1deg); }
}
@keyframes fc-phoenix-sparks {
  0%, 100% { opacity: 0.55; }
  35%      { opacity: 1;    }
  70%      { opacity: 0.75; }
}

.fc-encircle-size-xs.fc-encircle-phoenix::before,
.fc-encircle-size-xs.fc-encircle-phoenix::after,
.fc-encircle-size-sm.fc-encircle-phoenix::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 7 — CRYSTAL (§15.3 new variant)
   ════════════════════════════════════════════════════════════════════
   Faceted gemstone refraction. Like Obsidian's faceted look but bright
   white/silver core with intense rainbow refraction. Each facet is a
   sharp narrow peak with full saturation. Animated rotation slower than
   Obsidian (90s vs 60s) for an "always polished" feel.
*/

.fc-encircle-shadow_chancellor.fc-encircle-crystal .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(240, 248, 255, 0.55),
    inset 0 6px 18px -8px rgba(255, 255, 255, 0.95),
    0 0 0 1.5px rgba(220, 240, 255, 0.95),
    0 0 0 2.5px rgba(40, 50, 70, 1),
    0 0 20px 2px rgba(180, 220, 255, 0.45);
}
.fc-encircle-shadow_chancellor.fc-encircle-crystal:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(240, 248, 255, 0.7),
    inset 0 8px 22px -8px rgba(255, 255, 255, 1),
    0 0 0 2px rgba(255, 255, 255, 1),
    0 0 0 3px rgba(40, 50, 70, 1),
    0 0 30px 3px rgba(220, 240, 255, 0.75);
}
.fc-encircle-shadow_chancellor.fc-encircle-crystal .fc-encircle-avatar-fallback {
  background:
    /* Iridescent diagonal facet */
    linear-gradient(135deg,
      rgba(220, 240, 255, 0.7) 0%,
      rgba(167, 139, 250, 0.42) 22%,
      rgba(252, 165, 165, 0.42) 48%,
      rgba(125, 211, 252, 0.42) 72%,
      rgba(220, 240, 255, 0.7) 100%),
    /* Cross facet */
    linear-gradient(45deg,
      transparent 45%, rgba(255, 255, 255, 0.32) 50%, transparent 55%),
    /* Deep core */
    linear-gradient(180deg, rgba(30, 40, 60, 1) 0%, rgba(10, 14, 24, 1) 100%);
  color: rgba(248, 250, 255, 0.98);
  text-shadow:
    0 0 8px rgba(167, 139, 250, 0.7),
    0 0 14px rgba(125, 211, 252, 0.5);
}

/* 8 sharp colorful prismatic shards, brighter than obsidian.
   Whites + pure rainbow stops cycling around the rim. */
.fc-encircle-shadow_chancellor.fc-encircle-crystal::before {
  content: '';
  position: absolute;
  inset: -24%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    transparent 16deg,
    rgba(220, 240, 255, 0.65) 20deg,
    rgba(255, 255, 255, 1) 22.5deg,
    rgba(125, 211, 252, 0.85) 25deg,
    transparent 30deg,
    transparent 61deg,
    rgba(244, 114, 182, 0.65) 65deg,
    rgba(255, 255, 255, 1) 67.5deg,
    rgba(167, 139, 250, 0.85) 70deg,
    transparent 75deg,
    transparent 106deg,
    rgba(74, 222, 128, 0.65) 110deg,
    rgba(255, 255, 255, 1) 112.5deg,
    rgba(34, 211, 238, 0.85) 115deg,
    transparent 120deg,
    transparent 151deg,
    rgba(254, 215, 170, 0.65) 155deg,
    rgba(255, 255, 255, 1) 157.5deg,
    rgba(252, 211, 77, 0.85) 160deg,
    transparent 165deg,
    transparent 196deg,
    rgba(196, 181, 253, 0.65) 200deg,
    rgba(255, 255, 255, 0.95) 202.5deg,
    rgba(244, 114, 182, 0.85) 205deg,
    transparent 210deg,
    transparent 241deg,
    rgba(125, 211, 252, 0.65) 245deg,
    rgba(255, 255, 255, 0.95) 247.5deg,
    rgba(74, 222, 128, 0.85) 250deg,
    transparent 255deg,
    transparent 286deg,
    rgba(252, 211, 77, 0.65) 290deg,
    rgba(255, 255, 255, 0.95) 292.5deg,
    rgba(254, 215, 170, 0.85) 295deg,
    transparent 300deg,
    transparent 331deg,
    rgba(34, 211, 238, 0.65) 335deg,
    rgba(255, 255, 255, 0.95) 337.5deg,
    rgba(167, 139, 250, 0.85) 340deg,
    transparent 345deg,
    transparent 360deg
  );
  filter: blur(0.3px);
  -webkit-mask: radial-gradient(circle, transparent 41%, black 49%, transparent 66%);
          mask: radial-gradient(circle, transparent 41%, black 49%, transparent 66%);
  animation: fc-crystal-shift 90s linear infinite;
}

/* Sparkle dots — 4 tiny bright pinpoints that twinkle at offset phases.
   Positions evenly spaced to make the crystal feel cleanly cut. */
.fc-encircle-shadow_chancellor.fc-encircle-crystal::after {
  content: '';
  position: absolute;
  inset: -4%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 4% 4% at 50% 0%,
      rgba(255, 255, 255, 1) 0%,
      rgba(220, 240, 255, 0.5) 30%,
      transparent 60%),
    radial-gradient(ellipse 3.4% 3.4% at 100% 50%,
      rgba(255, 255, 255, 1) 0%, transparent 65%),
    radial-gradient(ellipse 4% 4% at 50% 100%,
      rgba(255, 255, 255, 1) 0%, transparent 65%),
    radial-gradient(ellipse 3.4% 3.4% at 0% 50%,
      rgba(255, 255, 255, 1) 0%, transparent 65%);
  filter: blur(0.4px);
  animation: fc-crystal-sparkle 2.2s ease-in-out infinite;
}

@keyframes fc-crystal-shift {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-crystal-sparkle {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  35%      { opacity: 1;    transform: scale(1.15); }
  70%      { opacity: 0.85; transform: scale(0.95); }
}

.fc-encircle-size-xs.fc-encircle-crystal::before,
.fc-encircle-size-xs.fc-encircle-crystal::after,
.fc-encircle-size-sm.fc-encircle-crystal::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 8 — BLACKHOLE (§18 new variant — REPLACES avatar)
   ════════════════════════════════════════════════════════════════════
   The avatar circle BECOMES a black hole. The frame interior is pure
   jet black; a vibrant orange/red accretion ring surrounds it; an
   asymmetric photon arc highlights the lensing. Outer halo extends
   far for the "drowning in space" feel. The avatar's identity is
   intentionally subsumed — the user IS the singularity.
*/

.fc-encircle-shadow_chancellor.fc-encircle-blackhole .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%,
      #000 0%, #000 76%,
      rgba(38, 8, 0, 1) 100%);
  box-shadow:
    /* Innermost soft photon ring — bright orange-yellow at the very rim */
    inset 0 0 0 1.5px rgba(254, 215, 170, 0.95),
    /* Inset corona — orange falls off inward (event-horizon haze) */
    inset 0 0 18px -4px rgba(251, 146, 60, 0.85),
    /* Outer bright accretion-disk band */
    0 0 0 2px rgba(254, 215, 170, 0.85),
    /* Crimson outer ring */
    0 0 0 3.5px rgba(220, 38, 38, 0.7),
    /* Deep falloff into nothingness */
    0 0 32px 6px rgba(251, 146, 60, 0.75),
    0 0 56px 12px rgba(220, 38, 38, 0.42);
  animation: fc-blackhole-pulse 6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-blackhole:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 251, 235, 1),
    inset 0 0 24px -4px rgba(252, 165, 165, 1),
    0 0 0 2.5px rgba(255, 251, 235, 1),
    0 0 0 4px rgba(220, 38, 38, 0.85),
    0 0 44px 8px rgba(254, 215, 170, 0.9),
    0 0 70px 14px rgba(220, 38, 38, 0.6);
}

/* The singularity element — pure black core with a tiny inner ring of
   bent light suggesting matter being drawn in. Sits inside the frame. */
.fc-blackhole-core {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: radial-gradient(circle at 50% 50%, #000 60%, rgba(15, 0, 5, 1) 100%);
  border-radius: 50%;
  z-index: 1;
}
.fc-blackhole-singularity {
  width: 18%;
  height: 18%;
  border-radius: 50%;
  background: radial-gradient(circle, #000 50%, rgba(254, 215, 170, 0.25) 75%, transparent 100%);
  box-shadow: 0 0 8px rgba(254, 215, 170, 0.3);
  animation: fc-blackhole-singularity 3.2s ease-in-out infinite;
}

/* Outer accretion disk — elongated ellipse via scaleX (gravitational
   lensing). Brighter on the upper edge to suggest the photon ring. */
.fc-encircle-shadow_chancellor.fc-encircle-blackhole::before {
  content: '';
  position: absolute;
  inset: -38%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Outer faint dust */
    radial-gradient(circle, transparent 32%,
      rgba(220, 38, 38, 0.12) 33%, transparent 37%),
    /* Mid accretion ring */
    radial-gradient(circle, transparent 38%,
      rgba(251, 146, 60, 0.55) 42%,
      rgba(254, 215, 170, 0.7) 45%,
      rgba(251, 146, 60, 0.55) 48%,
      transparent 52%),
    /* Inner photon halo (bright lensed light) */
    radial-gradient(circle, transparent 51%,
      rgba(254, 215, 170, 0.8) 54%,
      transparent 58%);
  filter: blur(0.7px) saturate(1.4);
  transform: scaleX(1.08);
  animation: fc-blackhole-disk 22s linear infinite;
}

/* Asymmetric photon-ring highlight — bright arc at top-left where lensed
   light from the rear of the disk wraps over. Interstellar reference. */
.fc-encircle-shadow_chancellor.fc-encircle-blackhole::after {
  content: '';
  position: absolute;
  inset: -22%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Top-left bright arc — the bent light from behind */
    radial-gradient(ellipse 34% 28% at 26% 18%,
      rgba(255, 251, 235, 0.85) 0%,
      rgba(254, 215, 170, 0.7) 25%,
      rgba(251, 146, 60, 0.45) 50%,
      transparent 70%),
    /* Lensing mirror (dimmer, bottom-right) */
    radial-gradient(ellipse 24% 20% at 76% 84%,
      rgba(252, 165, 165, 0.55) 0%,
      rgba(220, 38, 38, 0.3) 35%,
      transparent 62%),
    /* Bright top edge sliver — photon ring intensification */
    radial-gradient(ellipse 65% 16% at 50% 12%,
      rgba(254, 243, 199, 0.55) 0%,
      rgba(252, 211, 77, 0.35) 30%,
      transparent 60%);
  filter: blur(0.6px);
  -webkit-mask: radial-gradient(circle, transparent 36%, black 46%, black 60%, transparent 64%);
          mask: radial-gradient(circle, transparent 36%, black 46%, black 60%, transparent 64%);
  animation: fc-blackhole-photon 4.6s ease-in-out infinite;
}

@keyframes fc-blackhole-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1.5px rgba(254, 215, 170, 0.95),
      inset 0 0 18px -4px rgba(251, 146, 60, 0.85),
      0 0 0 2px rgba(254, 215, 170, 0.85),
      0 0 0 3.5px rgba(220, 38, 38, 0.7),
      0 0 32px 6px rgba(251, 146, 60, 0.75),
      0 0 56px 12px rgba(220, 38, 38, 0.42);
  }
  50% {
    box-shadow:
      inset 0 0 0 2px rgba(255, 251, 235, 1),
      inset 0 0 22px -3px rgba(252, 165, 165, 0.92),
      0 0 0 2.5px rgba(255, 251, 235, 1),
      0 0 0 4px rgba(220, 38, 38, 0.85),
      0 0 42px 8px rgba(254, 215, 170, 0.85),
      0 0 70px 14px rgba(220, 38, 38, 0.55);
  }
}
@keyframes fc-blackhole-disk {
  from { transform: scaleX(1.08) rotate(0deg); }
  to   { transform: scaleX(1.08) rotate(360deg); }
}
@keyframes fc-blackhole-photon {
  0%, 100% { opacity: 0.85; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.03); }
}
@keyframes fc-blackhole-singularity {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.4); }
}

.fc-encircle-size-xs.fc-encircle-blackhole::before,
.fc-encircle-size-xs.fc-encircle-blackhole::after,
.fc-encircle-size-sm.fc-encircle-blackhole::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 9 — HALLOWEEN (§18 new variant — skull mask overlay)
   ════════════════════════════════════════════════════════════════════
   Inline-SVG skull mask sits ABOVE the avatar (z 4), occluding the
   initials/img with a bone-white skull silhouette. Glowing red eye
   sockets pulse. Frame gets a bronze/copper bezel for the haunted
   antique feel. xs/sm hide the SVG (detail unreadable).
*/

.fc-encircle-shadow_chancellor.fc-encircle-halloween .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, rgba(20, 8, 4, 1) 0%, rgba(0, 0, 0, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 0 14px -4px rgba(251, 146, 60, 0.55),
    /* Copper/bronze bezel ring */
    0 0 0 1.5px rgba(184, 115, 51, 0.88),
    /* Black gap */
    0 0 0 2.5px rgba(20, 8, 4, 1),
    /* Outer orange jack-o-lantern glow */
    0 0 18px 2px rgba(251, 146, 60, 0.5);
  animation: fc-halloween-glow 3.2s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-halloween:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 0 20px -4px rgba(252, 165, 165, 0.85),
    0 0 0 2px rgba(252, 165, 165, 1),
    0 0 0 3px rgba(20, 8, 4, 1),
    0 0 28px 3px rgba(220, 38, 38, 0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-halloween .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 100% 60% at 50% 70%, rgba(127, 29, 29, 0.45) 0%, transparent 70%),
    radial-gradient(ellipse 80% 40% at 50% 10%, rgba(251, 146, 60, 0.32) 0%, transparent 65%),
    linear-gradient(180deg, rgba(28, 10, 4, 1) 0%, rgba(8, 0, 0, 1) 100%);
  color: rgba(254, 215, 170, 0.92);
  text-shadow: 0 0 8px rgba(220, 38, 38, 0.65);
}

/* The mask itself — positioned ABSOLUTELY inside the frame, occupies
   the full frame area, z above avatar. */
.fc-halloween-mask {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 4;
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.65));
}
.fc-halloween-mask svg {
  width: 92%;
  height: 92%;
  display: block;
}

/* Animations for skull elements — sockets pulse, teeth flicker rarely */
.fc-skull-socket {
  transform-origin: center;
}
.fc-skull-socket-left { animation: fc-halloween-socket 2.4s ease-in-out 0.0s infinite; }
.fc-skull-socket-right { animation: fc-halloween-socket 2.4s ease-in-out 0.15s infinite; }

@keyframes fc-halloween-glow {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 0 14px -4px rgba(251, 146, 60, 0.55),
      0 0 0 1.5px rgba(184, 115, 51, 0.88),
      0 0 0 2.5px rgba(20, 8, 4, 1),
      0 0 18px 2px rgba(251, 146, 60, 0.5);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 0 18px -4px rgba(252, 211, 77, 0.85),
      0 0 0 2px rgba(218, 165, 32, 1),
      0 0 0 3px rgba(20, 8, 4, 1),
      0 0 28px 3px rgba(251, 146, 60, 0.85);
  }
}
@keyframes fc-halloween-socket {
  0%, 100% { opacity: 0.85; transform: scale(1); }
  35%      { opacity: 1;    transform: scale(1.08); }
  65%      { opacity: 0.7;  transform: scale(0.96); }
}

.fc-encircle-size-xs.fc-halloween-mask,
.fc-encircle-size-sm.fc-halloween-mask { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 10 — INFERNO (§19 — dragon-fire, locked cosmetic)
   ════════════════════════════════════════════════════════════════════
   Angrier hotter Phoenix sibling. Charcoal-black core, crimson flame
   walls licking outward, falling sparks. Asymmetric — flame leans
   slightly upward like a draft. Pulse 3.4s + flicker 2.6s + spark 1.6s.
*/

.fc-encircle-shadow_chancellor.fc-encircle-inferno .fc-encircle-frame {
  background: radial-gradient(circle at 50% 60%, rgba(60, 18, 8, 1) 0%, rgba(15, 4, 0, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 -8px 16px -4px rgba(220, 38, 38, 0.85),
    0 0 0 1.5px rgba(248, 113, 113, 0.95),
    0 0 0 2.5px rgba(15, 4, 0, 1),
    0 -6px 24px -2px rgba(252, 165, 165, 0.7),
    0 0 28px 4px rgba(220, 38, 38, 0.65),
    0 0 50px 8px rgba(127, 29, 29, 0.5);
  animation: fc-inferno-pulse 3.4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-inferno:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 -10px 20px -4px rgba(252, 165, 165, 1),
    0 0 0 2px rgba(254, 215, 170, 1),
    0 0 0 3px rgba(15, 4, 0, 1),
    0 -10px 32px -2px rgba(254, 215, 170, 0.9),
    0 0 40px 6px rgba(220, 38, 38, 0.85),
    0 0 64px 10px rgba(127, 29, 29, 0.7);
}
.fc-encircle-shadow_chancellor.fc-encircle-inferno .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 90% 60% at 50% 100%, rgba(220, 38, 38, 0.45) 0%, transparent 65%),
    linear-gradient(180deg, rgba(40, 8, 0, 1) 0%, rgba(8, 0, 0, 1) 100%);
  color: rgba(254, 215, 170, 0.95);
  text-shadow: 0 0 10px rgba(251, 146, 60, 0.85);
}

/* Outer flame walls — 6 hotspots cycling around the rim with bright cores.
   Heavier blur (1.2px) + saturate(1.55) for the dragon-breath feel. */
.fc-encircle-shadow_chancellor.fc-encircle-inferno::before {
  content: '';
  position: absolute;
  inset: -34%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Top crown */
    radial-gradient(ellipse 26% 22% at 50% 8%,
      rgba(255, 251, 235, 0.85) 0%,
      rgba(252, 211, 77, 0.7) 22%,
      rgba(251, 146, 60, 0.55) 45%,
      rgba(220, 38, 38, 0.32) 70%, transparent 92%),
    /* Right upper */
    radial-gradient(ellipse 22% 28% at 88% 32%,
      rgba(254, 215, 170, 0.78) 0%,
      rgba(251, 146, 60, 0.55) 35%,
      rgba(220, 38, 38, 0.32) 65%, transparent 90%),
    /* Right lower */
    radial-gradient(ellipse 20% 24% at 86% 70%,
      rgba(254, 215, 170, 0.72) 0%,
      rgba(220, 38, 38, 0.45) 40%, transparent 85%),
    /* Bottom */
    radial-gradient(ellipse 26% 24% at 50% 92%,
      rgba(252, 165, 165, 0.7) 0%,
      rgba(220, 38, 38, 0.45) 40%, transparent 78%),
    /* Left lower */
    radial-gradient(ellipse 20% 24% at 14% 70%,
      rgba(254, 215, 170, 0.72) 0%,
      rgba(220, 38, 38, 0.45) 40%, transparent 85%),
    /* Left upper */
    radial-gradient(ellipse 22% 28% at 12% 32%,
      rgba(254, 215, 170, 0.78) 0%,
      rgba(251, 146, 60, 0.55) 35%,
      rgba(220, 38, 38, 0.32) 65%, transparent 90%);
  filter: blur(1.2px) saturate(1.55);
  -webkit-mask: radial-gradient(circle, transparent 38%, black 49%);
          mask: radial-gradient(circle, transparent 38%, black 49%);
  animation: fc-inferno-licks 2.6s ease-in-out infinite alternate;
}

/* Falling sparks — 6 hot pinpoint dots around the rim that pulse */
.fc-encircle-shadow_chancellor.fc-encircle-inferno::after {
  content: '';
  position: absolute;
  inset: -16%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 2.5% 2.5% at 26% 14%, rgba(252, 211, 77, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 3% 3% at 74% 18%, rgba(251, 146, 60, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.4% 2.4% at 92% 52%, rgba(254, 215, 170, 0.92) 0%, transparent 65%),
    radial-gradient(ellipse 2.8% 2.8% at 80% 82%, rgba(220, 38, 38, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.6% 2.6% at 18% 78%, rgba(252, 211, 77, 0.95) 0%, transparent 65%),
    radial-gradient(ellipse 2.8% 2.8% at 6% 44%, rgba(251, 146, 60, 0.95) 0%, transparent 65%);
  filter: blur(0.5px);
  animation: fc-inferno-sparks 1.6s ease-in-out infinite;
}

@keyframes fc-inferno-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 -8px 16px -4px rgba(220, 38, 38, 0.85),
      0 0 0 1.5px rgba(248, 113, 113, 0.95),
      0 0 0 2.5px rgba(15, 4, 0, 1),
      0 -6px 24px -2px rgba(252, 165, 165, 0.7),
      0 0 28px 4px rgba(220, 38, 38, 0.65),
      0 0 50px 8px rgba(127, 29, 29, 0.5);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 -10px 22px -4px rgba(252, 165, 165, 1),
      0 0 0 2px rgba(254, 215, 170, 1),
      0 0 0 3px rgba(15, 4, 0, 1),
      0 -10px 32px -2px rgba(254, 215, 170, 0.92),
      0 0 38px 6px rgba(220, 38, 38, 0.85),
      0 0 60px 10px rgba(127, 29, 29, 0.7);
  }
}
@keyframes fc-inferno-licks {
  0%   { transform: scale(1)    rotate(-2deg); opacity: 0.95; }
  50%  { transform: scale(1.04) rotate(0deg);  opacity: 1; }
  100% { transform: scale(1.02) rotate(2deg);  opacity: 0.97; }
}
@keyframes fc-inferno-sparks {
  0%, 100% { opacity: 0.5; }
  35%      { opacity: 1; }
  70%      { opacity: 0.75; }
}

.fc-encircle-size-xs.fc-encircle-inferno::before,
.fc-encircle-size-xs.fc-encircle-inferno::after,
.fc-encircle-size-sm.fc-encircle-inferno::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 11 — GLACIER (§19 — frozen counterpart, locked cosmetic)
   ════════════════════════════════════════════════════════════════════
   Cold mirror of Inferno. Pale-blue crystalline frost — 6 ice shards
   radiating outward (conic) + cold mist. Almost static (80s rotation).
   Frost rim highlight on the frame (suggests breath fogging the lens).
*/

.fc-encircle-shadow_chancellor.fc-encircle-glacier .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(220, 240, 255, 0.15) 0%, rgba(8, 16, 28, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.4),
    inset 0 6px 16px -6px rgba(220, 240, 255, 0.85),
    inset 0 -3px 10px -6px rgba(125, 211, 252, 0.5),
    0 0 0 1.5px rgba(220, 240, 255, 0.92),
    0 0 0 2.5px rgba(15, 25, 40, 1),
    0 0 18px 2px rgba(125, 211, 252, 0.45);
}
.fc-encircle-shadow_chancellor.fc-encircle-glacier:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.55),
    inset 0 8px 20px -6px rgba(255, 255, 255, 1),
    inset 0 -4px 12px -6px rgba(167, 243, 255, 0.7),
    0 0 0 2px rgba(255, 255, 255, 1),
    0 0 0 3px rgba(15, 25, 40, 1),
    0 0 28px 3px rgba(167, 243, 255, 0.7);
}
.fc-encircle-shadow_chancellor.fc-encircle-glacier .fc-encircle-avatar-fallback {
  background:
    linear-gradient(135deg,
      rgba(220, 240, 255, 0.6) 0%,
      rgba(15, 25, 40, 1) 50%,
      rgba(60, 90, 120, 0.4) 100%),
    linear-gradient(45deg,
      transparent 47%, rgba(255, 255, 255, 0.25) 50%, transparent 53%);
  color: rgba(220, 240, 255, 0.95);
  text-shadow:
    0 0 6px rgba(220, 240, 255, 0.85),
    0 0 12px rgba(125, 211, 252, 0.55);
}

/* 6 ice shards (conic peaks) cycling alternating white + ice-blue.
   Sharp transparent gaps between peaks — the crystalline feel. */
.fc-encircle-shadow_chancellor.fc-encircle-glacier::before {
  content: '';
  position: absolute;
  inset: -26%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    transparent 28deg,
    rgba(255, 255, 255, 0.85) 30deg,
    transparent 38deg,
    transparent 88deg,
    rgba(220, 240, 255, 0.78) 90deg,
    transparent 98deg,
    transparent 148deg,
    rgba(125, 211, 252, 0.85) 150deg,
    transparent 158deg,
    transparent 208deg,
    rgba(255, 255, 255, 0.78) 210deg,
    transparent 218deg,
    transparent 268deg,
    rgba(220, 240, 255, 0.85) 270deg,
    transparent 278deg,
    transparent 328deg,
    rgba(125, 211, 252, 0.78) 330deg,
    transparent 338deg,
    transparent 360deg
  );
  filter: blur(0.3px);
  -webkit-mask: radial-gradient(circle, transparent 41%, black 50%, transparent 64%);
          mask: radial-gradient(circle, transparent 41%, black 50%, transparent 64%);
  animation: fc-glacier-rotate 80s linear infinite;
}

/* Cold mist — soft outer haze top + bottom, blends via screen */
.fc-encircle-shadow_chancellor.fc-encircle-glacier::after {
  content: '';
  position: absolute;
  inset: -8%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 90% 30% at 50% 6%, rgba(220, 240, 255, 0.55) 0%, transparent 65%),
    radial-gradient(ellipse 80% 25% at 50% 100%, rgba(167, 243, 255, 0.4) 0%, transparent 60%);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 50%, transparent 56%);
          mask: radial-gradient(circle, transparent 44%, black 50%, transparent 56%);
  mix-blend-mode: screen;
}

@keyframes fc-glacier-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.fc-encircle-size-xs.fc-encircle-glacier::before,
.fc-encircle-size-xs.fc-encircle-glacier::after,
.fc-encircle-size-sm.fc-encircle-glacier::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 12 — MATRIX (§19 — green digital rain, locked cosmetic, SVG)
   ════════════════════════════════════════════════════════════════════
   "Follow the white rabbit." Vertical streams of falling green katakana
   glyphs above the avatar. mix-blend-mode: screen → phosphor-glow over
   the user's avatar. Frame is jet black with neon green bezel.
*/

.fc-encircle-shadow_chancellor.fc-encircle-matrix .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(0, 32, 8, 0.85) 0%, rgba(0, 12, 4, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(74, 222, 128, 0.45),
    inset 0 0 14px -4px rgba(0, 255, 80, 0.65),
    0 0 0 1.5px rgba(74, 222, 128, 0.92),
    0 0 0 2.5px rgba(0, 12, 4, 1),
    0 0 20px 2px rgba(74, 222, 128, 0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-matrix:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(167, 243, 208, 0.65),
    inset 0 0 18px -4px rgba(10, 255, 94, 0.85),
    0 0 0 2px rgba(167, 243, 208, 1),
    0 0 0 3px rgba(0, 12, 4, 1),
    0 0 30px 3px rgba(74, 222, 128, 0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-matrix .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 90% 60% at 50% 100%, rgba(34, 197, 94, 0.32) 0%, transparent 65%),
    linear-gradient(180deg, rgba(0, 18, 4, 1) 0%, rgba(0, 6, 0, 1) 100%);
  color: rgba(167, 243, 208, 0.98);
  text-shadow:
    0 0 6px rgba(10, 255, 94, 0.85),
    0 0 14px rgba(74, 222, 128, 0.55);
}

/* The SVG container — overlay above the avatar with screen blend. */
.fc-matrix-rain {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 4;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-matrix-rain svg {
  width: 100%;
  height: 100%;
  display: block;
}
.fc-matrix-glyph {
  font-family: 'IBM Plex Mono', 'Courier New', monospace;
  font-size: 9px;
  fill: url(#fc-matrix-fade);
  font-weight: 700;
}
.fc-matrix-glyph-head {
  fill: #d6ffd6;
  filter: drop-shadow(0 0 1.4px #0aff5e);
}

/* §20 polish: head glyph stronger glow + glitch flicker animation.
   The trailing fade is now handled via per-glyph SVG opacity attrs
   in the template (tail 0.15 → head 1.0). */
.fc-matrix-glyph-head {
  fill: #d6ffd6;
  filter: drop-shadow(0 0 2.2px #0aff5e) drop-shadow(0 0 4px rgba(10, 255, 94, 0.55));
  animation: fc-matrix-head-flicker 0.85s steps(2, jump-none) infinite;
}

/* Stream animations — translateY linear, infinite, offset phases.
   §20: 8 streams instead of 5, with greater speed variety (2.2-5.8s)
   for layered-depth feel. Streams 1,5,8 fast; 2,4,7 medium; 3,6 slow. */
.fc-matrix-stream-1 { animation: fc-matrix-fall 2.4s linear infinite; }
.fc-matrix-stream-2 { animation: fc-matrix-fall 4.2s linear -0.8s infinite; }
.fc-matrix-stream-3 { animation: fc-matrix-fall 5.6s linear -1.6s infinite; }
.fc-matrix-stream-4 { animation: fc-matrix-fall 3.8s linear -0.4s infinite; }
.fc-matrix-stream-5 { animation: fc-matrix-fall 2.8s linear -2.2s infinite; }
.fc-matrix-stream-6 { animation: fc-matrix-fall 5.2s linear -3.0s infinite; }
.fc-matrix-stream-7 { animation: fc-matrix-fall 3.4s linear -1.1s infinite; }
.fc-matrix-stream-8 { animation: fc-matrix-fall 4.6s linear -0.6s infinite; }

@keyframes fc-matrix-fall {
  0%   { transform: translateY(-50%); }
  100% { transform: translateY(110%); }
}

/* §20: head glyph "glitch" flicker — rapid opacity ping suggests the
   CRT phosphor lag where the bright leading char ghosts as it falls. */
@keyframes fc-matrix-head-flicker {
  0%, 80%, 100% { opacity: 1;    }
  20%           { opacity: 0.85; }
  40%           { opacity: 0.95; }
  60%           { opacity: 0.75; }
}

/* §20: subtle horizontal scanline drift on the overlay rect — barely
   perceptible, but it adds the analog-monitor feel as the bands creep. */
.fc-matrix-scanlines {
  animation: fc-matrix-scanlines-drift 8s linear infinite;
}
@keyframes fc-matrix-scanlines-drift {
  0%   { transform: translateY(0); }
  100% { transform: translateY(3px); }  /* one pattern-unit shift */
}

.fc-encircle-size-xs.fc-matrix-rain,
.fc-encircle-size-sm.fc-matrix-rain { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 13 — GALAXY (§19 — spiral arm starfield, locked cosmetic)
   ════════════════════════════════════════════════════════════════════
   Deep-space avatar with violet/cyan spiral arms wrapping around + bright
   yellow supernova flare at the top-right rim. 8 star pinpoints twinkle.
   Slow disk rotation 40s. Frame deep violet with supernova accent shadow.
*/

.fc-encircle-shadow_chancellor.fc-encircle-galaxy .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(15, 0, 25, 1) 0%, #000 100%);
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 0 14px -4px rgba(167, 139, 250, 0.65),
    0 0 0 1.5px rgba(196, 181, 253, 0.85),
    0 0 0 2.5px rgba(10, 0, 18, 1),
    0 0 28px 4px rgba(91, 33, 158, 0.55),
    /* Supernova accent at top-right edge — yellow-orange */
    10px -10px 32px 4px rgba(252, 211, 77, 0.55);
  animation: fc-galaxy-pulse 6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-galaxy:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(0, 0, 0, 0.95),
    inset 0 0 18px -4px rgba(216, 200, 255, 0.85),
    0 0 0 2px rgba(216, 200, 255, 1),
    0 0 0 3px rgba(10, 0, 18, 1),
    0 0 38px 5px rgba(91, 33, 158, 0.78),
    14px -14px 42px 4px rgba(254, 243, 199, 0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-galaxy .fc-encircle-avatar-fallback {
  background:
    radial-gradient(circle at 30% 30%, rgba(91, 33, 158, 0.55) 0%, rgba(15, 0, 25, 1) 60%, #000 100%),
    radial-gradient(ellipse 14% 12% at 78% 22%, rgba(252, 211, 77, 0.35) 0%, transparent 70%);
  color: rgba(220, 200, 255, 0.95);
  text-shadow:
    0 0 8px rgba(167, 139, 250, 0.7),
    0 0 16px rgba(125, 211, 252, 0.4);
}

/* Spiral arms — 2 conic-gradient sweeps with violet→cyan stops. Heavy blur
   + saturate so they read as gaseous nebula clouds. */
.fc-encircle-shadow_chancellor.fc-encircle-galaxy::before {
  content: '';
  position: absolute;
  inset: -32%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    transparent 0deg,
    rgba(196, 181, 253, 0.55) 30deg,
    rgba(125, 211, 252, 0.65) 50deg,
    rgba(196, 181, 253, 0.45) 80deg,
    transparent 120deg,
    transparent 180deg,
    rgba(196, 181, 253, 0.55) 210deg,
    rgba(125, 211, 252, 0.65) 230deg,
    rgba(196, 181, 253, 0.45) 260deg,
    transparent 300deg,
    transparent 360deg
  );
  filter: blur(2.4px) saturate(1.4);
  -webkit-mask: radial-gradient(circle, transparent 40%, black 48%, black 60%, transparent 68%);
          mask: radial-gradient(circle, transparent 40%, black 48%, black 60%, transparent 68%);
  animation: fc-galaxy-spin 40s linear infinite;
}

/* Supernova flare + 8 star pinpoints around the rim. The supernova is the
   focal accent — bright yellow-white core with orange falloff. Stars are
   tiny pinpoint bursts of pure white that twinkle in sync. */
.fc-encircle-shadow_chancellor.fc-encircle-galaxy::after {
  content: '';
  position: absolute;
  inset: -24%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* SUPERNOVA — bright yellow-white flare at top-right, brighter core */
    radial-gradient(ellipse 32% 28% at 80% 16%,
      rgba(255, 255, 245, 1) 0%,
      rgba(254, 243, 199, 0.95) 18%,
      rgba(252, 211, 77, 0.85) 38%,
      rgba(251, 146, 60, 0.55) 55%,
      rgba(220, 38, 38, 0.2) 75%,
      transparent 88%),
    /* 8 stars distributed around the rim — alternating bright + medium */
    radial-gradient(ellipse 2% 2% at 22% 14%, rgba(255, 255, 255, 1) 0%, transparent 60%),
    radial-gradient(ellipse 2.4% 2.4% at 88% 50%, rgba(255, 255, 255, 0.95) 0%, transparent 60%),
    radial-gradient(ellipse 2% 2% at 76% 82%, rgba(255, 255, 255, 1) 0%, transparent 60%),
    radial-gradient(ellipse 2.2% 2.2% at 24% 78%, rgba(255, 255, 255, 0.92) 0%, transparent 60%),
    radial-gradient(ellipse 2% 2% at 12% 44%, rgba(255, 255, 255, 1) 0%, transparent 60%),
    radial-gradient(ellipse 2.2% 2.2% at 50% 6%, rgba(255, 255, 255, 0.92) 0%, transparent 60%),
    radial-gradient(ellipse 1.8% 1.8% at 60% 96%, rgba(255, 255, 255, 0.88) 0%, transparent 60%),
    radial-gradient(ellipse 1.6% 1.6% at 4% 60%, rgba(255, 255, 255, 0.85) 0%, transparent 60%);
  filter: blur(0.4px);
  animation: fc-galaxy-twinkle 2.4s ease-in-out infinite;
}

@keyframes fc-galaxy-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 0 14px -4px rgba(167, 139, 250, 0.65),
      0 0 0 1.5px rgba(196, 181, 253, 0.85),
      0 0 0 2.5px rgba(10, 0, 18, 1),
      0 0 28px 4px rgba(91, 33, 158, 0.55),
      10px -10px 32px 4px rgba(252, 211, 77, 0.55);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.95),
      inset 0 0 18px -4px rgba(216, 200, 255, 0.85),
      0 0 0 2px rgba(216, 200, 255, 0.95),
      0 0 0 3px rgba(10, 0, 18, 1),
      0 0 38px 5px rgba(91, 33, 158, 0.78),
      14px -14px 40px 4px rgba(254, 243, 199, 0.85);
  }
}
@keyframes fc-galaxy-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-galaxy-twinkle {
  0%, 100% { opacity: 0.6; }
  50%      { opacity: 1;   }
}

.fc-encircle-size-xs.fc-encircle-galaxy::before,
.fc-encircle-size-xs.fc-encircle-galaxy::after,
.fc-encircle-size-sm.fc-encircle-galaxy::before { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 14 — INK (§19 — sumi-e calligraphy, locked cosmetic)
   ════════════════════════════════════════════════════════════════════
   Wet Japanese ink wash on cream paper. Black sumi-e brushstrokes
   trailing off the rim. A crimson seal stamp ("approved") sits at the
   bottom-right. NO rotation animation (calligraphy is static). Subtle
   6s seal pulse only.
*/

.fc-encircle-shadow_chancellor.fc-encircle-ink .fc-encircle-frame {
  background:
    radial-gradient(circle at 30% 30%, rgba(255, 252, 245, 1) 0%, rgba(240, 235, 222, 1) 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(15, 15, 18, 0.92),
    inset 0 -4px 12px -4px rgba(127, 29, 29, 0.35),
    0 0 0 2px rgba(15, 15, 18, 0.95),
    0 0 0 3px rgba(255, 252, 245, 0.85),
    0 0 0 4.5px rgba(15, 15, 18, 0.9),
    0 0 14px 2px rgba(127, 29, 29, 0.45);
}
.fc-encircle-shadow_chancellor.fc-encircle-ink:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(15, 15, 18, 1),
    inset 0 -6px 16px -4px rgba(127, 29, 29, 0.55),
    0 0 0 2.5px rgba(15, 15, 18, 1),
    0 0 0 4px rgba(255, 252, 245, 1),
    0 0 0 5.5px rgba(15, 15, 18, 1),
    0 0 22px 3px rgba(220, 38, 38, 0.7);
}
.fc-encircle-shadow_chancellor.fc-encircle-ink .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 60% 40% at 30% 30%, rgba(255, 252, 245, 1) 0%, transparent 70%),
    linear-gradient(160deg, rgba(240, 235, 222, 1) 0%, rgba(210, 200, 180, 1) 100%);
  color: rgba(15, 15, 18, 0.92);
  text-shadow: 0 1px 2px rgba(127, 29, 29, 0.32);
}

/* Sumi-e wash halo + 4 asymmetric brushstrokes. The halo is a CREAM-PAPER
   donut (so the black brushstrokes can read against it — without a paper
   layer, they'd vanish on the dark card background). Brushstrokes layer
   on top of the paper, organic and asymmetric. */
.fc-encircle-shadow_chancellor.fc-encircle-ink::before {
  content: '';
  position: absolute;
  inset: -32%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Top brushstroke — darker, dominant horizontal sweep */
    radial-gradient(ellipse 38% 16% at 50% 14%, rgba(15, 15, 18, 0.95) 0%, rgba(15, 15, 18, 0.45) 35%, transparent 78%),
    /* Right thick vertical drip */
    radial-gradient(ellipse 14% 30% at 88% 42%, rgba(15, 15, 18, 0.95) 0%, rgba(15, 15, 18, 0.45) 35%, transparent 75%),
    /* Bottom-left organic wash */
    radial-gradient(ellipse 30% 22% at 18% 86%, rgba(15, 15, 18, 0.92) 0%, rgba(15, 15, 18, 0.4) 38%, transparent 78%),
    /* Crimson seal smudge near the bottom-right edge */
    radial-gradient(ellipse 14% 12% at 76% 76%, rgba(220, 38, 38, 0.85) 0%, rgba(127, 29, 29, 0.4) 50%, transparent 80%),
    /* CREAM PAPER donut behind the brushstrokes (so they have contrast) */
    radial-gradient(circle, transparent 36%, rgba(255, 252, 245, 0.95) 42%, rgba(240, 235, 222, 0.85) 56%, transparent 68%);
  filter: blur(0.6px);
  -webkit-mask: radial-gradient(circle, transparent 36%, black 44%, black 68%, transparent 76%);
          mask: radial-gradient(circle, transparent 36%, black 44%, black 68%, transparent 76%);
}

/* The seal — a crimson hanko stamp at lower-right of the avatar */
.fc-encircle-shadow_chancellor.fc-encircle-ink::after {
  content: '';
  position: absolute;
  width: 32%;
  height: 32%;
  bottom: -6%;
  right: -6%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 4;  /* above the avatar */
  background:
    radial-gradient(circle, rgba(220, 38, 38, 0.95) 0%, rgba(127, 29, 29, 0.82) 35%, transparent 70%);
  box-shadow:
    inset 0 0 0 1px rgba(80, 14, 14, 0.65),
    0 0 6px 1px rgba(220, 38, 38, 0.5);
  filter: blur(0.4px);
  animation: fc-ink-seal 6s ease-in-out infinite;
}

@keyframes fc-ink-seal {
  0%, 100% { opacity: 0.95; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.04); }
}

.fc-encircle-size-xs.fc-encircle-ink::before,
.fc-encircle-size-xs.fc-encircle-ink::after,
.fc-encircle-size-sm.fc-encircle-ink::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 15 — CIRCUIT (§19 — neon cyberpunk, locked cosmetic)
   ════════════════════════════════════════════════════════════════════
   Glowing geometric circuit traces around the avatar. Cyan/magenta/yellow
   accents on jet black. 4 data-flow pinpoints pulse along the cardinals.
   Traces pulse 1.8s + flow 1.4s. Heavy neon glow on the frame.
*/

.fc-encircle-shadow_chancellor.fc-encircle-circuit .fc-encircle-frame {
  background:
    linear-gradient(135deg, rgba(0, 12, 18, 1) 0%, rgba(0, 4, 8, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(34, 211, 238, 0.85),
    inset 0 0 14px -4px rgba(34, 211, 238, 0.85),
    0 0 0 1.5px rgba(34, 211, 238, 1),
    0 0 0 2.5px rgba(0, 12, 18, 1),
    -7px 7px 22px 0 rgba(244, 114, 182, 0.5),
    7px -7px 22px 0 rgba(252, 211, 77, 0.5),
    0 0 28px 3px rgba(34, 211, 238, 0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-circuit:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(125, 252, 255, 1),
    inset 0 0 20px -4px rgba(125, 252, 255, 1),
    0 0 0 2px rgba(125, 252, 255, 1),
    0 0 0 3px rgba(0, 12, 18, 1),
    -10px 10px 30px 0 rgba(244, 114, 182, 0.8),
    10px -10px 30px 0 rgba(254, 240, 138, 0.8),
    0 0 40px 4px rgba(34, 211, 238, 0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-circuit .fc-encircle-avatar-fallback {
  background:
    linear-gradient(135deg, rgba(0, 18, 28, 1) 0%, rgba(0, 4, 8, 1) 100%),
    radial-gradient(circle at 70% 30%, rgba(34, 211, 238, 0.18) 0%, transparent 60%);
  color: rgba(125, 252, 255, 0.98);
  text-shadow:
    0 0 6px rgba(34, 211, 238, 0.95),
    0 0 14px rgba(244, 114, 182, 0.55);
}

/* Conic-gradient traces with sharp neon stops at 8 angles
   (alternating cyan/magenta/yellow). Wider band per trace (16-20deg)
   for visibility — too thin and they disappear against dark bg. */
.fc-encircle-shadow_chancellor.fc-encircle-circuit::before {
  content: '';
  position: absolute;
  inset: -28%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    /* Top — cyan */
    transparent 342deg, rgba(34, 211, 238, 1) 350deg, rgba(125, 252, 255, 1) 0deg, rgba(34, 211, 238, 1) 10deg, transparent 18deg,
    /* NE — yellow */
    transparent 38deg, rgba(252, 211, 77, 0.95) 44deg, rgba(254, 240, 138, 1) 50deg, rgba(252, 211, 77, 0.95) 56deg, transparent 62deg,
    /* E — magenta */
    transparent 82deg, rgba(244, 114, 182, 0.98) 88deg, rgba(251, 207, 232, 1) 95deg, rgba(244, 114, 182, 0.98) 102deg, transparent 108deg,
    /* SE — cyan */
    transparent 128deg, rgba(34, 211, 238, 0.98) 134deg, rgba(125, 252, 255, 1) 141deg, rgba(34, 211, 238, 0.98) 148deg, transparent 154deg,
    /* S — yellow */
    transparent 174deg, rgba(252, 211, 77, 0.95) 180deg, rgba(254, 240, 138, 1) 187deg, rgba(252, 211, 77, 0.95) 194deg, transparent 200deg,
    /* SW — magenta */
    transparent 218deg, rgba(244, 114, 182, 0.98) 224deg, rgba(251, 207, 232, 1) 231deg, rgba(244, 114, 182, 0.98) 238deg, transparent 244deg,
    /* W — cyan */
    transparent 262deg, rgba(34, 211, 238, 1) 268deg, rgba(125, 252, 255, 1) 275deg, rgba(34, 211, 238, 1) 282deg, transparent 288deg,
    /* NW — yellow */
    transparent 308deg, rgba(252, 211, 77, 0.95) 314deg, rgba(254, 240, 138, 1) 321deg, rgba(252, 211, 77, 0.95) 328deg, transparent 334deg,
    transparent 360deg
  );
  filter: blur(0.4px) saturate(1.3);
  -webkit-mask: radial-gradient(circle, transparent 40%, black 49%, transparent 62%);
          mask: radial-gradient(circle, transparent 40%, black 49%, transparent 62%);
  animation: fc-circuit-pulse 1.8s ease-in-out infinite;
}

/* Data-flow pinpoints — 4 small pulsing dots at the cardinals */
.fc-encircle-shadow_chancellor.fc-encircle-circuit::after {
  content: '';
  position: absolute;
  inset: -8%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 3% 3% at 50% 4%, rgba(34, 211, 238, 1) 0%, transparent 60%),
    radial-gradient(ellipse 3% 3% at 96% 50%, rgba(244, 114, 182, 1) 0%, transparent 60%),
    radial-gradient(ellipse 3% 3% at 50% 96%, rgba(252, 211, 77, 1) 0%, transparent 60%),
    radial-gradient(ellipse 3% 3% at 4% 50%, rgba(34, 211, 238, 1) 0%, transparent 60%);
  filter: blur(0.5px) drop-shadow(0 0 4px rgba(34, 211, 238, 0.8));
  animation: fc-circuit-flow 1.4s ease-in-out infinite;
}

@keyframes fc-circuit-pulse {
  0%, 100% { opacity: 0.85; }
  50%      { opacity: 1;    }
}
@keyframes fc-circuit-flow {
  0%, 100% { opacity: 0.6; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.18); }
}

.fc-encircle-size-xs.fc-encircle-circuit::before,
.fc-encircle-size-xs.fc-encircle-circuit::after,
.fc-encircle-size-sm.fc-encircle-circuit::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 16 — YULE (§20 — winter solstice / holiday, seasonal locked)
   ════════════════════════════════════════════════════════════════════
   Winter night. Deep midnight blue core with falling silver snowflake
   pinpoints + warm gold ribbon glow at the rim + soft red ember at top
   (yule log fire memory). Cold + warm together = holiday magic.
*/

.fc-encircle-shadow_chancellor.fc-encircle-yule .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 30%, rgba(15, 22, 50, 1) 0%, rgba(6, 10, 26, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(220, 240, 255, 0.55),
    inset 0 6px 14px -6px rgba(255, 255, 255, 0.85),
    /* Snow-white rim */
    0 0 0 1.5px rgba(248, 250, 255, 0.95),
    /* Black gap */
    0 0 0 2.5px rgba(6, 10, 26, 1),
    /* Warm gold outer halo (yule log warmth) */
    0 -6px 22px -2px rgba(252, 211, 77, 0.6),
    /* Soft red ember */
    0 -10px 30px 2px rgba(220, 38, 38, 0.32),
    /* Cool blue outer wash */
    0 8px 20px 2px rgba(125, 211, 252, 0.4);
  animation: fc-yule-glow 5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-yule:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.85),
    inset 0 8px 18px -6px rgba(255, 255, 255, 1),
    0 0 0 2px rgba(255, 255, 255, 1),
    0 0 0 3px rgba(6, 10, 26, 1),
    0 -10px 32px -2px rgba(254, 215, 170, 0.9),
    0 -14px 40px 2px rgba(252, 165, 165, 0.55),
    0 10px 28px 2px rgba(167, 243, 255, 0.6);
}
.fc-encircle-shadow_chancellor.fc-encircle-yule .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 80% 50% at 50% 100%, rgba(252, 211, 77, 0.22) 0%, transparent 65%),
    radial-gradient(ellipse 70% 40% at 50% 0%, rgba(220, 38, 38, 0.18) 0%, transparent 60%),
    linear-gradient(180deg, rgba(15, 22, 50, 1) 0%, rgba(6, 10, 26, 1) 100%);
  color: rgba(248, 250, 255, 0.96);
  text-shadow:
    0 0 8px rgba(254, 215, 170, 0.7),
    0 0 16px rgba(220, 38, 38, 0.32);
}

/* 8 snowflake pinpoints scattered around the rim — soft white blobs */
.fc-encircle-shadow_chancellor.fc-encircle-yule::before {
  content: '';
  position: absolute;
  inset: -22%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    radial-gradient(ellipse 3% 3% at 18% 14%, rgba(255, 255, 255, 0.98) 0%, rgba(220, 240, 255, 0.45) 35%, transparent 70%),
    radial-gradient(ellipse 2.5% 2.5% at 50% 6%, rgba(255, 255, 255, 0.92) 0%, transparent 65%),
    radial-gradient(ellipse 2.8% 2.8% at 82% 12%, rgba(255, 255, 255, 0.95) 0%, rgba(220, 240, 255, 0.4) 40%, transparent 70%),
    radial-gradient(ellipse 2.4% 2.4% at 94% 48%, rgba(255, 255, 255, 0.9) 0%, transparent 65%),
    radial-gradient(ellipse 3% 3% at 84% 80%, rgba(255, 255, 255, 0.92) 0%, rgba(220, 240, 255, 0.4) 35%, transparent 70%),
    radial-gradient(ellipse 2.6% 2.6% at 50% 92%, rgba(255, 255, 255, 0.88) 0%, transparent 65%),
    radial-gradient(ellipse 3% 3% at 16% 82%, rgba(255, 255, 255, 0.95) 0%, rgba(220, 240, 255, 0.4) 35%, transparent 70%),
    radial-gradient(ellipse 2.4% 2.4% at 6% 48%, rgba(255, 255, 255, 0.92) 0%, transparent 65%);
  filter: blur(0.4px);
  animation: fc-yule-snow 6s ease-in-out infinite;
}

/* Warm gold ribbon at top + soft warm wash at bottom (hearth fire) */
.fc-encircle-shadow_chancellor.fc-encircle-yule::after {
  content: '';
  position: absolute;
  inset: -10%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Top gold ribbon */
    radial-gradient(ellipse 70% 22% at 50% 4%,
      rgba(254, 243, 199, 0.78) 0%,
      rgba(252, 211, 77, 0.55) 30%,
      rgba(220, 38, 38, 0.18) 60%, transparent 85%),
    /* Bottom hearth warmth */
    radial-gradient(ellipse 70% 24% at 50% 100%,
      rgba(252, 165, 165, 0.5) 0%,
      rgba(252, 211, 77, 0.32) 35%, transparent 75%);
  filter: blur(0.6px);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
          mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
  mix-blend-mode: screen;
}

@keyframes fc-yule-glow {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(220, 240, 255, 0.55),
      inset 0 6px 14px -6px rgba(255, 255, 255, 0.85),
      0 0 0 1.5px rgba(248, 250, 255, 0.95),
      0 0 0 2.5px rgba(6, 10, 26, 1),
      0 -6px 22px -2px rgba(252, 211, 77, 0.6),
      0 -10px 30px 2px rgba(220, 38, 38, 0.32),
      0 8px 20px 2px rgba(125, 211, 252, 0.4);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(255, 255, 255, 0.7),
      inset 0 8px 18px -6px rgba(255, 255, 255, 1),
      0 0 0 2px rgba(255, 255, 255, 1),
      0 0 0 3px rgba(6, 10, 26, 1),
      0 -10px 30px -2px rgba(254, 215, 170, 0.85),
      0 -14px 36px 2px rgba(252, 165, 165, 0.45),
      0 10px 26px 2px rgba(167, 243, 255, 0.55);
  }
}
@keyframes fc-yule-snow {
  0%, 100% { transform: translateY(0); opacity: 0.92; }
  50%      { transform: translateY(2px); opacity: 1; }
}

.fc-encircle-size-xs.fc-encircle-yule::before,
.fc-encircle-size-xs.fc-encircle-yule::after,
.fc-encircle-size-sm.fc-encircle-yule::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 17 — SAKURA (§20 — spring cherry blossom, seasonal locked)
   ════════════════════════════════════════════════════════════════════
   Soft cherry blossom petals drifting against a pale cream backdrop.
   Warm pink + ivory + a hint of new-leaf green. Calm, hopeful, the
   season of renewal. Petals drift gently sideways.
*/

.fc-encircle-shadow_chancellor.fc-encircle-sakura .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(255, 240, 245, 1) 0%, rgba(248, 215, 230, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.65),
    inset 0 4px 12px -4px rgba(255, 255, 255, 0.85),
    /* Cherry-blossom pink rim */
    0 0 0 1.5px rgba(251, 207, 232, 0.95),
    /* Cream gap */
    0 0 0 2.5px rgba(255, 245, 248, 0.95),
    /* Soft outer pink halo */
    0 0 22px 3px rgba(244, 114, 182, 0.4);
}
.fc-encircle-shadow_chancellor.fc-encircle-sakura:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.85),
    inset 0 6px 16px -4px rgba(255, 255, 255, 1),
    0 0 0 2px rgba(255, 255, 255, 1),
    0 0 0 3px rgba(255, 245, 248, 1),
    0 0 32px 4px rgba(244, 114, 182, 0.7);
}
.fc-encircle-shadow_chancellor.fc-encircle-sakura .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 80% 50% at 30% 30%, rgba(255, 255, 255, 0.7) 0%, transparent 65%),
    linear-gradient(180deg, rgba(255, 240, 245, 1) 0%, rgba(248, 215, 230, 1) 100%);
  color: rgba(127, 29, 79, 0.85);
  text-shadow: 0 0 8px rgba(255, 255, 255, 0.85);
}

/* 8 drifting petals — pink ellipses slightly tilted, scattered around rim */
.fc-encircle-shadow_chancellor.fc-encircle-sakura::before {
  content: '';
  position: absolute;
  inset: -28%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Top pair */
    radial-gradient(ellipse 5% 3% at 30% 8%, rgba(251, 207, 232, 0.92) 0%, rgba(244, 114, 182, 0.55) 40%, transparent 78%),
    radial-gradient(ellipse 4% 6% at 64% 4%, rgba(255, 230, 240, 0.95) 0%, rgba(251, 207, 232, 0.6) 40%, transparent 78%),
    /* Right side */
    radial-gradient(ellipse 6% 4% at 92% 32%, rgba(244, 114, 182, 0.85) 0%, rgba(244, 114, 182, 0.4) 45%, transparent 80%),
    radial-gradient(ellipse 4% 5% at 96% 64%, rgba(251, 207, 232, 0.9) 0%, transparent 70%),
    /* Bottom pair */
    radial-gradient(ellipse 5% 3% at 70% 92%, rgba(255, 230, 240, 0.95) 0%, rgba(251, 207, 232, 0.6) 40%, transparent 78%),
    radial-gradient(ellipse 6% 4% at 34% 96%, rgba(244, 114, 182, 0.85) 0%, rgba(244, 114, 182, 0.4) 45%, transparent 80%),
    /* Left side */
    radial-gradient(ellipse 4% 6% at 8% 64%, rgba(255, 230, 240, 0.9) 0%, transparent 70%),
    radial-gradient(ellipse 5% 3% at 4% 30%, rgba(251, 207, 232, 0.92) 0%, rgba(244, 114, 182, 0.55) 40%, transparent 78%);
  filter: blur(0.6px) saturate(1.15);
  animation: fc-sakura-drift 14s ease-in-out infinite alternate;
}

/* Inner highlight — soft sakura bloom + green-leaf hints */
.fc-encircle-shadow_chancellor.fc-encircle-sakura::after {
  content: '';
  position: absolute;
  inset: -8%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 50% 32% at 50% 6%,
      rgba(255, 255, 255, 0.65) 0%,
      rgba(251, 207, 232, 0.35) 50%, transparent 80%),
    /* Faint green leaf tone at left */
    radial-gradient(ellipse 18% 10% at 8% 50%,
      rgba(187, 247, 208, 0.55) 0%, transparent 75%);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
          mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
  mix-blend-mode: multiply;
}

@keyframes fc-sakura-drift {
  0%   { transform: translateX(-3%) translateY(0)   rotate(-2deg); }
  100% { transform: translateX(3%)  translateY(2px) rotate(2deg); }
}

.fc-encircle-size-xs.fc-encircle-sakura::before,
.fc-encircle-size-xs.fc-encircle-sakura::after,
.fc-encircle-size-sm.fc-encircle-sakura::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 18 — SOLSTICE (§20 — summer sunburst, seasonal locked)
   ════════════════════════════════════════════════════════════════════
   Mid-summer sun. Bright golden core radiating 8 sunburst rays + a soft
   golden wave undulation along the bottom (heat shimmer + ocean horizon).
   Hot, bright, vivid. The opposite of Yule.
*/

.fc-encircle-shadow_chancellor.fc-encircle-solstice .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(254, 240, 138, 0.85) 0%, rgba(254, 215, 170, 0.95) 60%, rgba(120, 53, 15, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(120, 53, 15, 0.55),
    inset 0 -8px 18px -4px rgba(254, 243, 199, 0.95),
    /* Golden rim */
    0 0 0 1.5px rgba(252, 211, 77, 1),
    /* Amber gap */
    0 0 0 2.5px rgba(120, 53, 15, 1),
    /* Hot outer aura */
    0 0 30px 5px rgba(252, 211, 77, 0.75),
    0 0 56px 10px rgba(251, 146, 60, 0.42);
  animation: fc-solstice-pulse 4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-solstice:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(120, 53, 15, 0.7),
    inset 0 -10px 22px -4px rgba(255, 255, 255, 1),
    0 0 0 2px rgba(255, 255, 245, 1),
    0 0 0 3px rgba(120, 53, 15, 1),
    0 0 42px 6px rgba(254, 243, 199, 0.95),
    0 0 70px 12px rgba(251, 146, 60, 0.6);
}
.fc-encircle-shadow_chancellor.fc-encircle-solstice .fc-encircle-avatar-fallback {
  background:
    radial-gradient(circle at 50% 60%, rgba(255, 255, 245, 0.8) 0%, rgba(254, 215, 170, 0.6) 50%, rgba(120, 53, 15, 0.6) 100%);
  color: rgba(120, 53, 15, 0.95);
  text-shadow:
    0 0 8px rgba(254, 243, 199, 1),
    0 0 16px rgba(252, 211, 77, 0.6);
}

/* 8 sunburst rays via conic-gradient — wide bright peaks at cardinals
   and diagonals, fading at the edges to make star-shape clear. */
.fc-encircle-shadow_chancellor.fc-encircle-solstice::before {
  content: '';
  position: absolute;
  inset: -36%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background: conic-gradient(
    from 0deg,
    /* N */
    transparent 340deg, rgba(254, 243, 199, 0.9) 350deg, rgba(255, 255, 245, 1) 0deg, rgba(252, 211, 77, 0.9) 10deg, transparent 20deg,
    /* NE */
    transparent 40deg, rgba(254, 243, 199, 0.78) 45deg, rgba(255, 255, 245, 0.95) 53deg, rgba(252, 211, 77, 0.78) 60deg, transparent 66deg,
    /* E */
    transparent 84deg, rgba(254, 243, 199, 0.85) 88deg, rgba(255, 255, 245, 1) 95deg, rgba(252, 211, 77, 0.85) 102deg, transparent 108deg,
    /* SE */
    transparent 128deg, rgba(254, 243, 199, 0.78) 133deg, rgba(255, 255, 245, 0.95) 140deg, rgba(252, 211, 77, 0.78) 147deg, transparent 153deg,
    /* S */
    transparent 174deg, rgba(254, 243, 199, 0.85) 178deg, rgba(255, 255, 245, 1) 185deg, rgba(252, 211, 77, 0.85) 192deg, transparent 198deg,
    /* SW */
    transparent 218deg, rgba(254, 243, 199, 0.78) 223deg, rgba(255, 255, 245, 0.95) 230deg, rgba(252, 211, 77, 0.78) 237deg, transparent 243deg,
    /* W */
    transparent 262deg, rgba(254, 243, 199, 0.85) 268deg, rgba(255, 255, 245, 1) 275deg, rgba(252, 211, 77, 0.85) 282deg, transparent 288deg,
    /* NW */
    transparent 308deg, rgba(254, 243, 199, 0.78) 313deg, rgba(255, 255, 245, 0.95) 320deg, rgba(252, 211, 77, 0.78) 327deg, transparent 333deg,
    transparent 360deg
  );
  filter: blur(1.2px) saturate(1.4);
  -webkit-mask: radial-gradient(circle, transparent 38%, black 50%, transparent 78%);
          mask: radial-gradient(circle, transparent 38%, black 50%, transparent 78%);
  animation: fc-solstice-rays 40s linear infinite;
}

/* Heat-shimmer bands + golden wave undulation along bottom */
.fc-encircle-shadow_chancellor.fc-encircle-solstice::after {
  content: '';
  position: absolute;
  inset: -16%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    /* Top corona — bright halo */
    radial-gradient(ellipse 60% 22% at 50% 8%,
      rgba(255, 255, 255, 0.85) 0%,
      rgba(254, 243, 199, 0.55) 35%, transparent 75%),
    /* Bottom golden ocean wave */
    radial-gradient(ellipse 60% 24% at 50% 96%,
      rgba(251, 146, 60, 0.65) 0%,
      rgba(252, 211, 77, 0.4) 40%, transparent 78%);
  filter: blur(0.8px);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
          mask: radial-gradient(circle, transparent 44%, black 50%, transparent 60%);
  animation: fc-solstice-shimmer 3.2s ease-in-out infinite alternate;
}

@keyframes fc-solstice-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1px rgba(120, 53, 15, 0.55),
      inset 0 -8px 18px -4px rgba(254, 243, 199, 0.95),
      0 0 0 1.5px rgba(252, 211, 77, 1),
      0 0 0 2.5px rgba(120, 53, 15, 1),
      0 0 30px 5px rgba(252, 211, 77, 0.75),
      0 0 56px 10px rgba(251, 146, 60, 0.42);
  }
  50% {
    box-shadow:
      inset 0 0 0 1px rgba(120, 53, 15, 0.7),
      inset 0 -10px 22px -4px rgba(255, 255, 255, 1),
      0 0 0 2px rgba(255, 255, 245, 1),
      0 0 0 3px rgba(120, 53, 15, 1),
      0 0 40px 6px rgba(254, 243, 199, 0.92),
      0 0 64px 11px rgba(251, 146, 60, 0.58);
  }
}
@keyframes fc-solstice-rays {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-solstice-shimmer {
  from { opacity: 0.85; transform: scale(1); }
  to   { opacity: 1;    transform: scale(1.02); }
}

.fc-encircle-size-xs.fc-encircle-solstice::before,
.fc-encircle-size-xs.fc-encircle-solstice::after,
.fc-encircle-size-sm.fc-encircle-solstice::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT 19 — HARVEST (§20 — autumn maple, seasonal locked)
   ════════════════════════════════════════════════════════════════════
   Early autumn. Warm amber/orange/red maple leaves drifting downward.
   Brown-amber core, harvest warmth. The bridge between Solstice (summer)
   and Halloween (late October's spooky moment).
*/

.fc-encircle-shadow_chancellor.fc-encircle-harvest .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 40%, rgba(120, 53, 15, 0.95) 0%, rgba(60, 26, 5, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(120, 53, 15, 0.9),
    inset 0 4px 14px -4px rgba(251, 146, 60, 0.65),
    /* Burnt-orange rim */
    0 0 0 1.5px rgba(234, 88, 12, 1),
    /* Dark gap */
    0 0 0 2.5px rgba(60, 26, 5, 1),
    /* Warm amber outer halo */
    0 0 24px 3px rgba(234, 88, 12, 0.6),
    0 0 48px 6px rgba(180, 83, 9, 0.35);
}
.fc-encircle-shadow_chancellor.fc-encircle-harvest:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1px rgba(180, 83, 9, 1),
    inset 0 6px 18px -4px rgba(252, 211, 77, 0.85),
    0 0 0 2px rgba(254, 215, 170, 1),
    0 0 0 3px rgba(60, 26, 5, 1),
    0 0 34px 4px rgba(254, 215, 170, 0.85),
    0 0 60px 8px rgba(234, 88, 12, 0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-harvest .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 80% 50% at 30% 30%, rgba(252, 165, 165, 0.4) 0%, transparent 60%),
    linear-gradient(180deg, rgba(120, 53, 15, 0.95) 0%, rgba(60, 26, 5, 1) 100%);
  color: rgba(254, 215, 170, 0.96);
  text-shadow:
    0 0 8px rgba(234, 88, 12, 0.85),
    0 0 16px rgba(127, 29, 29, 0.55);
}

/* 7 maple-leaf-shaped drifting blobs, alternating amber/orange/crimson */
.fc-encircle-shadow_chancellor.fc-encircle-harvest::before {
  content: '';
  position: absolute;
  inset: -28%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 1;
  background:
    /* Top leaves */
    radial-gradient(ellipse 6% 5% at 26% 10%, rgba(252, 211, 77, 0.9) 0%, rgba(234, 88, 12, 0.55) 45%, transparent 80%),
    radial-gradient(ellipse 5% 6% at 60% 6%, rgba(234, 88, 12, 0.92) 0%, rgba(180, 83, 9, 0.6) 45%, transparent 80%),
    /* Right cluster */
    radial-gradient(ellipse 7% 5% at 90% 36%, rgba(220, 38, 38, 0.85) 0%, rgba(127, 29, 29, 0.5) 45%, transparent 80%),
    radial-gradient(ellipse 5% 6% at 92% 70%, rgba(252, 211, 77, 0.85) 0%, rgba(234, 88, 12, 0.5) 45%, transparent 80%),
    /* Bottom cluster */
    radial-gradient(ellipse 6% 5% at 50% 96%, rgba(234, 88, 12, 0.92) 0%, rgba(127, 29, 29, 0.55) 45%, transparent 80%),
    radial-gradient(ellipse 6% 5% at 18% 86%, rgba(254, 215, 170, 0.88) 0%, rgba(251, 146, 60, 0.5) 45%, transparent 80%),
    /* Left side */
    radial-gradient(ellipse 5% 6% at 6% 42%, rgba(220, 38, 38, 0.85) 0%, rgba(127, 29, 29, 0.5) 45%, transparent 80%);
  filter: blur(0.5px) saturate(1.3);
  animation: fc-harvest-drift 12s ease-in-out infinite alternate;
}

/* Inner warm amber underglow + soft golden top sheen */
.fc-encircle-shadow_chancellor.fc-encircle-harvest::after {
  content: '';
  position: absolute;
  inset: -10%;
  border-radius: 50%;
  pointer-events: none;
  z-index: 2;
  background:
    radial-gradient(ellipse 70% 20% at 50% 6%,
      rgba(254, 243, 199, 0.55) 0%,
      rgba(252, 211, 77, 0.32) 40%, transparent 78%),
    radial-gradient(ellipse 70% 24% at 50% 100%,
      rgba(234, 88, 12, 0.6) 0%,
      rgba(127, 29, 29, 0.35) 40%, transparent 78%);
  -webkit-mask: radial-gradient(circle, transparent 44%, black 50%, transparent 62%);
          mask: radial-gradient(circle, transparent 44%, black 50%, transparent 62%);
  mix-blend-mode: screen;
}

@keyframes fc-harvest-drift {
  0%   { transform: translateY(0)   rotate(-2deg); }
  100% { transform: translateY(3px) rotate(2deg); }
}

.fc-encircle-size-xs.fc-encircle-harvest::before,
.fc-encircle-size-xs.fc-encircle-harvest::after,
.fc-encircle-size-sm.fc-encircle-harvest::after { display: none; }

/* ════════════════════════════════════════════════════════════════════
   xl size — push halos further outward for maximum drama on profile cards
   ════════════════════════════════════════════════════════════════════ */
.fc-encircle-size-xl.fc-encircle-goth::before    { inset: -32%; filter: blur(1.9px) saturate(1.4); }
.fc-encircle-size-xl.fc-encircle-goth::after     { inset: -14%; }
.fc-encircle-size-xl.fc-encircle-obsidian::before { inset: -26%; filter: blur(0.5px); }
.fc-encircle-size-xl.fc-encircle-obsidian::after  { inset: -7%; }
.fc-encircle-size-xl.fc-encircle-void::before     { inset: -36%; }
.fc-encircle-size-xl.fc-encircle-void::after      { inset: -22%; }
.fc-encircle-size-xl.fc-encircle-aurora::before   { inset: -32%; filter: blur(2.8px) saturate(1.4); }
.fc-encircle-size-xl.fc-encircle-aurora::after    { inset: -16%; filter: blur(1.6px); }
.fc-encircle-size-xl.fc-encircle-phoenix::before  { inset: -36%; filter: blur(1.4px) saturate(1.35); }
.fc-encircle-size-xl.fc-encircle-phoenix::after   { inset: -18%; }
.fc-encircle-size-xl.fc-encircle-crystal::before  { inset: -28%; filter: blur(0.4px); }
.fc-encircle-size-xl.fc-encircle-crystal::after   { inset: -5%; }
/* §18: blackhole gets deeper outer halo at xl + photon ring intensified */
.fc-encircle-size-xl.fc-encircle-blackhole::before { inset: -44%; filter: blur(0.9px) saturate(1.5); }
.fc-encircle-size-xl.fc-encircle-blackhole::after  { inset: -26%; }
/* §18: halloween mask doesn't need ::before/::after overrides (no halo
   layers — the mask itself is the focal point). The frame box-shadow
   handles the orange glow. */

/* §19 xl overrides — push halos further out for the 6 new variants.
   Inferno + Glacier + Galaxy + Ink + Circuit all use ::before halos that
   benefit from deeper inset at xl. Matrix is an SVG overlay (inset 0
   stays), so it doesn't need an xl tweak. */
.fc-encircle-size-xl.fc-encircle-inferno::before { inset: -38%; filter: blur(1.4px) saturate(1.6); }
.fc-encircle-size-xl.fc-encircle-inferno::after  { inset: -18%; }
.fc-encircle-size-xl.fc-encircle-glacier::before { inset: -30%; filter: blur(0.4px); }
.fc-encircle-size-xl.fc-encircle-glacier::after  { inset: -10%; }
.fc-encircle-size-xl.fc-encircle-galaxy::before  { inset: -36%; filter: blur(2.8px) saturate(1.5); }
.fc-encircle-size-xl.fc-encircle-galaxy::after   { inset: -22%; }
.fc-encircle-size-xl.fc-encircle-ink::before     { inset: -24%; filter: blur(1.0px); }
.fc-encircle-size-xl.fc-encircle-ink::after      { width: 36%; height: 36%; bottom: -8%; right: -8%; }
.fc-encircle-size-xl.fc-encircle-circuit::before { inset: -26%; filter: blur(0.5px); }
.fc-encircle-size-xl.fc-encircle-circuit::after  { inset: -10%; }
/* §20 xl overrides — seasonal wave (yule/sakura/solstice/harvest) */
.fc-encircle-size-xl.fc-encircle-yule::before    { inset: -26%; }
.fc-encircle-size-xl.fc-encircle-yule::after     { inset: -12%; }
.fc-encircle-size-xl.fc-encircle-sakura::before  { inset: -32%; filter: blur(0.8px) saturate(1.2); }
.fc-encircle-size-xl.fc-encircle-sakura::after   { inset: -10%; }
.fc-encircle-size-xl.fc-encircle-solstice::before { inset: -42%; filter: blur(1.6px) saturate(1.5); }
.fc-encircle-size-xl.fc-encircle-solstice::after  { inset: -20%; }
.fc-encircle-size-xl.fc-encircle-harvest::before { inset: -32%; filter: blur(0.7px) saturate(1.4); }
.fc-encircle-size-xl.fc-encircle-harvest::after  { inset: -12%; }

/* ════════════════════════════════════════════════════════════════════
   VARIANT — GLITCH v3 (§21 — Sovereign-themed corruption, refined)
   ════════════════════════════════════════════════════════════════════
   Refined from v2 after Commander feedback (2026-05-12):
     • REMOVED ghost text spans (caused "two chars colliding" mess).
       RGB split is now ONLY via drop-shadow filter on the avatar.
     • Slice bands → IRREGULAR data-tear strips (varying widths/positions),
       not full-width rings (which read as decoration, not corruption).
     • Colors → theme tokens: --nc-danger crimson + --nc-primary cyan
       on --nc-void near-black. Cohesive with the sovereign dark UI.
     • Added 3 tiny rotated-square corruption marks that echo the
       TheProtocol brand mark (lp-brand-mark-core diamond).
     • Cycle stretched 7.3s → 8.4s for less frantic feel.
     • Major burst events at 16% / 47% / 78% (3 events, varied severity).
*/

/* === FRAME RING — sovereign-themed chromatic aberration + 3 burst events === */
.fc-overlay-glitch .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(6, 8, 16, 0.98) 0%, rgba(2, 4, 10, 1) 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(255, 51, 102, 0.42),
    inset 0 0 20px -2px rgba(160, 30, 70, 0.62),
    -3px 0 0 1.5px rgba(255, 51, 102, 0.95),
    0 0 0 3px rgba(6, 8, 16, 1),
    3px 0 0 4.5px rgba(0, 210, 210, 0.95),
    -8px 0 22px rgba(255, 51, 102, 0.62),
    8px 0 22px rgba(0, 210, 210, 0.55),
    0 0 36px 4px rgba(120, 30, 90, 0.42);
  animation:
    fc-glitch-ring-breathe 2.4s ease-in-out infinite alternate,
    fc-glitch-ring-burst 8.4s linear infinite;
  overflow: hidden;
}
.fc-overlay-glitch:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 51, 102, 0.58),
    inset 0 0 26px -1px rgba(200, 40, 90, 0.78),
    -5px 0 0 2px rgba(255, 51, 102, 1),
    0 0 0 3.5px rgba(6, 8, 16, 1),
    5px 0 0 5.5px rgba(0, 210, 210, 1),
    -12px 0 28px rgba(255, 51, 102, 0.85),
    12px 0 28px rgba(0, 210, 210, 0.78),
    0 0 50px 6px rgba(150, 40, 110, 0.58);
}

/* === AVATAR INITIALS — RGB split via drop-shadow filter (THE marker) === */
/* Sovereign palette. No duplicate text — drop-shadow gives clean RGB ghosts
   that follow the glyph silhouette without any character collision mess. */
.fc-overlay-glitch .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 90% 70% at 50% 50%,
      rgba(40, 8, 24, 0.55) 0%, rgba(6, 8, 16, 1) 60%, #000308 100%);
  color: rgba(232, 234, 237, 1);
  text-shadow:
    0 0 6px rgba(0, 210, 210, 0.42),
    0 0 2px rgba(255, 255, 255, 0.85);
  filter:
    drop-shadow(-3px 0 0 rgba(255, 51, 102, 0.95))
    drop-shadow(3px 0 0 rgba(0, 210, 210, 0.88));
  animation: fc-glitch-text-rgb 3.1s ease-in-out infinite;
}

/* === AVATAR IMG — same drop-shadow treatment, tamer for photos === */
.fc-overlay-glitch .fc-encircle-avatar-img {
  filter:
    drop-shadow(-3px 0 0 rgba(255, 51, 102, 0.78))
    drop-shadow(3px 0 0 rgba(0, 210, 210, 0.72))
    saturate(1.25)
    contrast(1.08);
  animation: fc-glitch-img-rgb 3.1s ease-in-out infinite;
}

/* === OVERLAY CONTAINER === */
.fc-glitch-v3 {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
}
.fc-glitch-v3 .fc-glitch-svg {
  width: 100%;
  height: 100%;
  display: block;
  mix-blend-mode: screen;
}

/* === CRT VIGNETTE — sovereign void darken === */
.fc-glitch-vignette-v3 {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(
    ellipse 110% 110% at 50% 50%,
    transparent 52%,
    rgba(6, 8, 16, 0.62) 100%
  );
  z-index: 6;
}

/* === SCANLINES — always visible, slow drift === */
.fc-glitch-scanlines-v3 { animation: fc-glitch-scan-drift-v3 5.1s linear infinite; }
@keyframes fc-glitch-scan-drift-v3 {
  0%   { transform: translateY(0); }
  100% { transform: translateY(3px); }
}

/* === CRT SCAN BEAM — top to bottom === */
.fc-glitch-crt-beam-v3 { animation: fc-glitch-crt-sweep-v3 3.7s linear infinite; opacity: 0; }
@keyframes fc-glitch-crt-sweep-v3 {
  0%   { transform: translateY(-2px); opacity: 0; }
  10%  { opacity: 0.55; }
  90%  { opacity: 0.55; }
  100% { transform: translateY(102px); opacity: 0; }
}

/* === IRREGULAR DATA TEAR STRIPS — varying widths/positions/timings
       (NOT decorative rings — these read as actual data corruption) === */
.fc-glitch-tear-1 { animation: fc-glitch-tear1 1.9s steps(1) infinite; opacity: 0; transform-origin: left center; }
.fc-glitch-tear-2 { animation: fc-glitch-tear2 2.3s steps(1) infinite; opacity: 0; transform-origin: right center; }
.fc-glitch-tear-3 { animation: fc-glitch-tear3 2.7s steps(1) infinite; opacity: 0; transform-origin: left center; }
.fc-glitch-tear-4 { animation: fc-glitch-tear4 1.7s steps(1) infinite; opacity: 0; transform-origin: right center; }
.fc-glitch-tear-5 { animation: fc-glitch-tear5 3.3s steps(1) infinite; opacity: 0; transform-origin: left center; }
.fc-glitch-tear-6 { animation: fc-glitch-tear6 2.1s steps(1) infinite; opacity: 0; transform-origin: center; }
.fc-glitch-tear-7 { animation: fc-glitch-tear7 2.5s steps(1) infinite; opacity: 0; transform-origin: right center; }

@keyframes fc-glitch-tear1 {
  0%, 8% { opacity: 0; transform: translateX(0); }
  9%, 12% { opacity: 0.88; transform: translateX(-6px); }
  13%, 47% { opacity: 0; transform: translateX(0); }
  48%, 51% { opacity: 0.72; transform: translateX(-14px); }
  52%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-glitch-tear2 {
  0%, 14% { opacity: 0; transform: translateX(0); }
  15%, 18% { opacity: 0.82; transform: translateX(8px); }
  19%, 62% { opacity: 0; transform: translateX(0); }
  63%, 66% { opacity: 0.90; transform: translateX(18px); }
  67%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-glitch-tear3 {
  0%, 22% { opacity: 0; transform: translateX(0); }
  23%, 26% { opacity: 0.78; transform: translateX(-12px); }
  27%, 71% { opacity: 0; transform: translateX(0); }
  72%, 75% { opacity: 0.88; transform: translateX(-20px) scaleY(1.6); }
  76%, 100% { opacity: 0; transform: translateX(0) scaleY(1); }
}
@keyframes fc-glitch-tear4 {
  0%, 31% { opacity: 0; transform: translateX(0); }
  32%, 35% { opacity: 0.85; transform: translateX(10px); }
  36%, 82% { opacity: 0; transform: translateX(0); }
  83%, 86% { opacity: 0.78; transform: translateX(16px); }
  87%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-glitch-tear5 {
  0%, 6% { opacity: 0; transform: translateX(0) scaleY(1); }
  7%, 11% { opacity: 0.92; transform: translateX(-8px) scaleY(2); }
  12%, 54% { opacity: 0; transform: translateX(0) scaleY(1); }
  55%, 58% { opacity: 0.95; transform: translateX(-22px) scaleY(2.4); }
  59%, 100% { opacity: 0; transform: translateX(0) scaleY(1); }
}
@keyframes fc-glitch-tear6 {
  0%, 38% { opacity: 0; transform: translateX(0); }
  39%, 42% { opacity: 0.72; transform: translateX(12px); }
  43%, 78% { opacity: 0; transform: translateX(0); }
  79%, 82% { opacity: 0.85; transform: translateX(-14px); }
  83%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-glitch-tear7 {
  0%, 18% { opacity: 0; transform: translateX(0); }
  19%, 22% { opacity: 0.88; transform: translateX(14px); }
  23%, 66% { opacity: 0; transform: translateX(0); }
  67%, 70% { opacity: 0.78; transform: translateX(20px); }
  71%, 100% { opacity: 0; transform: translateX(0); }
}

/* === DIAMOND CORRUPTION MARKS — brand-mark echo, rapid flicker === */
.fc-glitch-diamond-1 { animation: fc-glitch-dia1 0.51s steps(2) infinite; opacity: 0; }
.fc-glitch-diamond-2 { animation: fc-glitch-dia2 0.73s steps(2) infinite; opacity: 0; }
.fc-glitch-diamond-3 { animation: fc-glitch-dia3 0.89s steps(2) infinite; opacity: 0; }
@keyframes fc-glitch-dia1 { 0%, 78% { opacity: 0; } 80%, 100% { opacity: 0.88; } }
@keyframes fc-glitch-dia2 { 0%, 82% { opacity: 0; } 84%, 100% { opacity: 0.85; } }
@keyframes fc-glitch-dia3 { 0%, 76% { opacity: 0; } 78%, 100% { opacity: 0.92; } }

/* === MAJOR BURST EVENTS — flash + displacement at 16% / 47% / 78% === */
.fc-glitch-flash-v3 { animation: fc-glitch-flash-v3 8.4s linear infinite; opacity: 0; }
@keyframes fc-glitch-flash-v3 {
  0%, 15.9% { opacity: 0; }
  16%, 16.2% { opacity: 0.82; }
  16.3%, 46.9% { opacity: 0; }
  47%, 47.2% { opacity: 0.42; }
  47.3%, 77.9% { opacity: 0; }
  78%, 78.3% { opacity: 1; }
  78.4%, 100% { opacity: 0; }
}

.fc-glitch-strip-major-1 { animation: fc-glitch-strip1 8.4s linear infinite; opacity: 0; }
.fc-glitch-strip-major-2 { animation: fc-glitch-strip2 8.4s linear infinite; opacity: 0; }
@keyframes fc-glitch-strip1 {
  0%, 15.9% { opacity: 0; transform: translateX(0); }
  16%, 16.2% { opacity: 0.92; transform: translateX(-22px); }
  16.3%, 77.9% { opacity: 0; transform: translateX(0); }
  78%, 78.3% { opacity: 1; transform: translateX(-30px); }
  78.4%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-glitch-strip2 {
  0%, 15.9% { opacity: 0; transform: translateX(0); }
  16%, 16.2% { opacity: 0.85; transform: translateX(18px); }
  16.3%, 77.9% { opacity: 0; transform: translateX(0); }
  78%, 78.3% { opacity: 0.95; transform: translateX(26px); }
  78.4%, 100% { opacity: 0; transform: translateX(0); }
}

/* === NOISE GRAIN — subtle, sovereign === */
.fc-glitch-noise-v3 { animation: fc-glitch-noise-v3 0.27s steps(3) infinite; }
@keyframes fc-glitch-noise-v3 {
  0%   { opacity: 0.14; }
  33%  { opacity: 0.26; }
  66%  { opacity: 0.10; }
  100% { opacity: 0.18; }
}

/* === GLYPH CORRUPTION — sovereign palette === */
.fc-glitch-glyph { opacity: 0; }
.fc-glitch-glyph-1 { animation: fc-glitch-glyph1 2.4s steps(10) infinite; }
.fc-glitch-glyph-2 { animation: fc-glitch-glyph2 1.9s steps(8) infinite; }
.fc-glitch-glyph-3 { animation: fc-glitch-glyph3 8.4s linear infinite; }
@keyframes fc-glitch-glyph1 {
  0%, 68% { opacity: 0; }
  70%, 73% { opacity: 0.78; }
  74%, 86% { opacity: 0; }
  87%, 90% { opacity: 0.85; }
  91%, 100% { opacity: 0; }
}
@keyframes fc-glitch-glyph2 {
  0%, 58% { opacity: 0; }
  60%, 63% { opacity: 0.72; }
  64%, 88% { opacity: 0; }
  89%, 92% { opacity: 0.82; }
  93%, 100% { opacity: 0; }
}
@keyframes fc-glitch-glyph3 {
  0%, 15.9% { opacity: 0; }
  16%, 16.3% { opacity: 0.85; }
  16.4%, 77.9% { opacity: 0; }
  78%, 78.3% { opacity: 1; }
  78.4%, 100% { opacity: 0; }
}

/* === ANIMATION DEFINITIONS — text/img RGB drift + ring breathing + bursts === */

/* Drop-shadow RGB oscillation on initials text (sovereign palette) */
@keyframes fc-glitch-text-rgb {
  0%, 100% {
    filter:
      drop-shadow(-3px 0 0 rgba(255, 51, 102, 0.95))
      drop-shadow(3px 0 0 rgba(0, 210, 210, 0.88));
  }
  22% {
    filter:
      drop-shadow(-5px 0 0 rgba(255, 51, 102, 0.95))
      drop-shadow(5px 0 0 rgba(0, 210, 210, 0.88));
  }
  35% {
    filter:
      drop-shadow(-9px 0 0 rgba(255, 51, 102, 1))
      drop-shadow(9px 0 0 rgba(0, 210, 210, 1));
  }
  50% {
    filter:
      drop-shadow(-2px 0 0 rgba(255, 51, 102, 0.85))
      drop-shadow(2px 0 0 rgba(0, 210, 210, 0.75));
  }
  72% {
    filter:
      drop-shadow(-4px 0 0 rgba(255, 51, 102, 0.95))
      drop-shadow(4px 0 0 rgba(0, 210, 210, 0.85));
  }
  86% {
    filter:
      drop-shadow(-13px 0 0 rgba(255, 51, 102, 1))
      drop-shadow(13px 0 0 rgba(0, 210, 210, 1));
  }
}

/* Same for img — softer to keep face legible */
@keyframes fc-glitch-img-rgb {
  0%, 100% {
    filter:
      drop-shadow(-3px 0 0 rgba(255, 51, 102, 0.78))
      drop-shadow(3px 0 0 rgba(0, 210, 210, 0.72))
      saturate(1.25) contrast(1.08);
  }
  35% {
    filter:
      drop-shadow(-6px 0 0 rgba(255, 51, 102, 0.85))
      drop-shadow(6px 0 0 rgba(0, 210, 210, 0.80))
      saturate(1.25) contrast(1.08);
  }
  72% {
    filter:
      drop-shadow(-4px 0 0 rgba(255, 51, 102, 0.82))
      drop-shadow(4px 0 0 rgba(0, 210, 210, 0.75))
      saturate(1.25) contrast(1.08);
  }
}

/* Frame ring breathing — gentle, sovereign-themed pulse */
@keyframes fc-glitch-ring-breathe {
  0% {
    box-shadow:
      inset 0 0 0 1.5px rgba(255, 51, 102, 0.42),
      inset 0 0 20px -2px rgba(160, 30, 70, 0.62),
      -3px 0 0 1.5px rgba(255, 51, 102, 0.95),
      0 0 0 3px rgba(6, 8, 16, 1),
      3px 0 0 4.5px rgba(0, 210, 210, 0.95),
      -8px 0 22px rgba(255, 51, 102, 0.62),
      8px 0 22px rgba(0, 210, 210, 0.55),
      0 0 36px 4px rgba(120, 30, 90, 0.42);
  }
  100% {
    box-shadow:
      inset 0 0 0 2px rgba(255, 51, 102, 0.55),
      inset 0 0 26px -1px rgba(190, 40, 90, 0.78),
      -4px 0 0 1.5px rgba(255, 70, 120, 1),
      0 0 0 3.5px rgba(6, 8, 16, 1),
      4px 0 0 5px rgba(20, 220, 220, 1),
      -10px 0 26px rgba(255, 51, 102, 0.78),
      10px 0 26px rgba(0, 210, 210, 0.68),
      0 0 46px 6px rgba(150, 40, 110, 0.58);
  }
}

/* Frame ring burst events — major corruption at 16% / 47% / 78% */
@keyframes fc-glitch-ring-burst {
  0%, 15.9%, 16.3%, 46.9%, 47.3%, 77.9%, 78.4%, 100% {
    /* normal — breathing animation drives box-shadow during these windows */
  }
  16%, 16.2% {
    box-shadow:
      inset 0 0 0 2.5px rgba(232, 234, 237, 0.88),
      inset 0 0 28px -1px rgba(255, 200, 220, 0.72),
      -12px 0 0 2px rgba(255, 51, 102, 1),
      0 0 0 4px rgba(6, 8, 16, 1),
      12px 0 0 6px rgba(0, 210, 210, 1),
      -18px 0 30px rgba(255, 51, 102, 0.92),
      18px 0 30px rgba(0, 210, 210, 0.88),
      0 0 60px 8px rgba(220, 100, 180, 0.78);
  }
  47%, 47.2% {
    box-shadow:
      inset 0 0 0 2px rgba(0, 255, 200, 0.65),
      inset 0 0 22px -2px rgba(0, 210, 210, 0.62),
      -8px 0 0 1.5px rgba(255, 51, 102, 1),
      0 0 0 3.5px rgba(6, 8, 16, 1),
      8px 0 0 5px rgba(0, 210, 210, 1),
      -14px 0 26px rgba(255, 51, 102, 0.85),
      14px 0 26px rgba(0, 210, 210, 0.80),
      0 0 42px 6px rgba(100, 30, 130, 0.62);
  }
  78%, 78.3% {
    box-shadow:
      inset 0 0 0 3.5px rgba(232, 234, 237, 1),
      inset 0 0 36px -1px rgba(232, 234, 237, 0.92),
      -20px 0 0 3px rgba(255, 51, 102, 1),
      0 0 0 5px rgba(6, 8, 16, 1),
      20px 0 0 7px rgba(0, 210, 210, 1),
      -28px 0 44px rgba(255, 51, 102, 1),
      28px 0 44px rgba(0, 210, 210, 1),
      0 0 80px 12px rgba(220, 80, 160, 0.95);
  }
}

/* ════════════════════════════════════════════════════════════════════
   VARIANT — CASCADE v1 (§26 — Matrix-style alien-code corruption)
   ════════════════════════════════════════════════════════════════════
   Sister to glitch but with a completely different visual language:
     • Asymmetric L/R corruption (left = vertical line tears, right =
       pixel blocks). Different shapes per side, different timing.
     • Uncoordinated prime-ratio cycles (0.7s / 1.3s / 2.1s / 3.7s)
       with steps() easing → never sync, never repeat. Reads as
       random malfunction not clocked breathing.
     • Persistent CJK glyph "hallucination layer" at 0.06-0.10 opacity
       in background of avatar. You have to STARE to notice them.
     • Major burst at 78% of 6.4s cycle: blackout + 4 columns of falling
       alien glyphs (CJK + box drawing + Greek + math + hex). 0.9s
       terminal cascade, ends abruptly. Different speeds per column =
       parallax. Pure terminal-green + cyan, no red.
     • Frame ring: subtle terminal-green inner glow, no chromatic split.
*/

/* === FRAME RING — terminal-green compromised glow === */
.fc-overlay-cascade .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%, rgba(0, 16, 8, 0.98) 0%, rgba(0, 6, 4, 1) 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(0, 255, 140, 0.42),
    inset 0 0 18px -2px rgba(0, 200, 110, 0.55),
    0 0 0 2.5px rgba(0, 6, 4, 1),
    0 0 22px 1px rgba(0, 255, 140, 0.52),
    0 0 40px 6px rgba(0, 200, 130, 0.32);
  animation:
    fc-cascade-ring-pulse 3.7s steps(8) infinite,
    fc-cascade-ring-burst 6.4s linear infinite;
  overflow: hidden;
}
.fc-overlay-cascade:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(0, 255, 140, 0.62),
    inset 0 0 26px -1px rgba(0, 220, 140, 0.78),
    0 0 0 3px rgba(0, 6, 4, 1),
    0 0 30px 2px rgba(0, 255, 140, 0.72),
    0 0 56px 8px rgba(0, 200, 130, 0.48);
}

/* === AVATAR INITIALS — milder RGB split, terminal-green leaning === */
.fc-overlay-cascade .fc-encircle-avatar-fallback {
  background:
    radial-gradient(ellipse 90% 70% at 50% 50%,
      rgba(0, 32, 16, 0.55) 0%, rgba(0, 8, 4, 1) 60%, #000 100%);
  color: rgba(232, 255, 240, 1);
  text-shadow:
    0 0 6px rgba(0, 255, 140, 0.48),
    0 0 2px rgba(255, 255, 255, 0.78);
  filter:
    drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.88))
    drop-shadow(2px 0 0 rgba(0, 210, 210, 0.78));
  animation: fc-cascade-text-jitter 2.1s steps(6) infinite;
}

/* === AVATAR IMG — same treatment, photo-friendly === */
.fc-overlay-cascade .fc-encircle-avatar-img {
  filter:
    drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.65))
    drop-shadow(2px 0 0 rgba(0, 210, 210, 0.60))
    saturate(1.15)
    hue-rotate(-8deg)
    contrast(1.08);
  animation: fc-cascade-img-jitter 2.1s steps(6) infinite;
}

/* === OVERLAY CONTAINER === */
.fc-cascade-v1 {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
}
.fc-cascade-v1 .fc-cascade-svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* === VIGNETTE — terminal-green inner darken === */
.fc-cascade-vignette {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  pointer-events: none;
  background: radial-gradient(
    ellipse 110% 110% at 50% 50%,
    transparent 55%,
    rgba(0, 8, 4, 0.65) 100%
  );
  z-index: 6;
}

/* === SCANLINES === */
.fc-cascade-scanlines { animation: fc-cascade-scan-drift 6.1s linear infinite; opacity: 0.85; }
@keyframes fc-cascade-scan-drift {
  0%   { transform: translateY(0); }
  100% { transform: translateY(3px); }
}

/* === HALLUCINATION LAYER — 8 CJK glyphs, faint, rapid steps flicker === */
/* Different cycle per glyph — prime ratios so they never sync. */
.fc-cascade-halu { opacity: 0; }
.fc-cascade-halu-1 { animation: fc-cascade-halu-a 4.1s steps(7) infinite; }
.fc-cascade-halu-2 { animation: fc-cascade-halu-b 3.7s steps(5) infinite; }
.fc-cascade-halu-3 { animation: fc-cascade-halu-c 5.3s steps(9) infinite; }
.fc-cascade-halu-4 { animation: fc-cascade-halu-d 2.9s steps(6) infinite; }
.fc-cascade-halu-5 { animation: fc-cascade-halu-e 6.7s steps(8) infinite; }
.fc-cascade-halu-6 { animation: fc-cascade-halu-f 4.7s steps(7) infinite; }
.fc-cascade-halu-7 { animation: fc-cascade-halu-g 3.1s steps(5) infinite; }
.fc-cascade-halu-8 { animation: fc-cascade-halu-h 5.9s steps(9) infinite; }
@keyframes fc-cascade-halu-a { 0%, 70% { opacity: 0; } 73%, 86% { opacity: 0.10; } 89%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-b { 0%, 55% { opacity: 0; } 58%, 72% { opacity: 0.08; } 75%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-c { 0%, 80% { opacity: 0; } 83%, 91% { opacity: 0.11; } 93%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-d { 0%, 40% { opacity: 0; } 43%, 58% { opacity: 0.09; } 62%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-e { 0%, 65% { opacity: 0; } 67%, 79% { opacity: 0.07; } 82%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-f { 0%, 25% { opacity: 0; } 28%, 41% { opacity: 0.10; } 44%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-g { 0%, 50% { opacity: 0; } 53%, 64% { opacity: 0.08; } 67%, 100% { opacity: 0; } }
@keyframes fc-cascade-halu-h { 0%, 35% { opacity: 0; } 38%, 51% { opacity: 0.11; } 54%, 100% { opacity: 0; } }

/* === LEFT-SIDE: vertical line tears, sharp steps() flicker === */
.fc-cascade-vtear-1 { animation: fc-cascade-vtear-a 1.3s steps(2) infinite; opacity: 0; }
.fc-cascade-vtear-2 { animation: fc-cascade-vtear-b 0.7s steps(2) infinite; opacity: 0; }
.fc-cascade-vtear-3 { animation: fc-cascade-vtear-c 2.1s steps(2) infinite; opacity: 0; }
.fc-cascade-vtear-4 { animation: fc-cascade-vtear-d 1.1s steps(2) infinite; opacity: 0; }
@keyframes fc-cascade-vtear-a { 0%, 78% { opacity: 0; transform: translateX(0); } 80%, 92% { opacity: 0.78; transform: translateX(2px); } 94%, 100% { opacity: 0; transform: translateX(0); } }
@keyframes fc-cascade-vtear-b { 0%, 62% { opacity: 0; transform: translateX(0); } 64%, 78% { opacity: 0.85; transform: translateX(-3px); } 80%, 100% { opacity: 0; transform: translateX(0); } }
@keyframes fc-cascade-vtear-c { 0%, 84% { opacity: 0; transform: translateX(0); } 86%, 95% { opacity: 0.72; transform: translateX(1px); } 96%, 100% { opacity: 0; transform: translateX(0); } }
@keyframes fc-cascade-vtear-d { 0%, 45% { opacity: 0; transform: translateX(0); } 47%, 62% { opacity: 0.82; transform: translateX(-2px); } 64%, 100% { opacity: 0; transform: translateX(0); } }

/* === RIGHT-SIDE: pixel blocks, different cycle, no transform === */
.fc-cascade-pxl-1 { animation: fc-cascade-pxl-a 0.9s steps(2) infinite; opacity: 0; }
.fc-cascade-pxl-2 { animation: fc-cascade-pxl-b 1.7s steps(2) infinite; opacity: 0; }
.fc-cascade-pxl-3 { animation: fc-cascade-pxl-c 1.1s steps(2) infinite; opacity: 0; }
.fc-cascade-pxl-4 { animation: fc-cascade-pxl-d 2.3s steps(2) infinite; opacity: 0; }
.fc-cascade-pxl-5 { animation: fc-cascade-pxl-e 0.7s steps(2) infinite; opacity: 0; }
@keyframes fc-cascade-pxl-a { 0%, 72% { opacity: 0; } 74%, 88% { opacity: 0.88; } 90%, 100% { opacity: 0; } }
@keyframes fc-cascade-pxl-b { 0%, 55% { opacity: 0; } 58%, 72% { opacity: 0.92; } 74%, 100% { opacity: 0; } }
@keyframes fc-cascade-pxl-c { 0%, 81% { opacity: 0; } 83%, 91% { opacity: 0.78; } 93%, 100% { opacity: 0; } }
@keyframes fc-cascade-pxl-d { 0%, 40% { opacity: 0; } 42%, 58% { opacity: 0.85; } 61%, 100% { opacity: 0; } }
@keyframes fc-cascade-pxl-e { 0%, 65% { opacity: 0; } 67%, 79% { opacity: 0.95; } 82%, 100% { opacity: 0; } }

/* === BURST: blackout + 4-column cascading code === */
/* The blackout rect covers everything (mix-blend-mode multiply darkens
   everything below it). Active only during the 0.9s burst window. */
.fc-cascade-blackout {
  animation: fc-cascade-blackout 6.4s linear infinite;
  opacity: 0;
  mix-blend-mode: multiply;
}
@keyframes fc-cascade-blackout {
  0%, 77.9% { opacity: 0; }
  78%, 86% { opacity: 0.95; }
  86.1%, 100% { opacity: 0; }
}

/* 4 cascade columns. Each one is OFF except during the burst window,
   and during the burst each translates downward at a slightly
   different speed (parallax). */
.fc-cascade-col { opacity: 0; }
.fc-cascade-col-1 { animation: fc-cascade-col-1 6.4s linear infinite; }
.fc-cascade-col-2 { animation: fc-cascade-col-2 6.4s linear infinite; }
.fc-cascade-col-3 { animation: fc-cascade-col-3 6.4s linear infinite; }
.fc-cascade-col-4 { animation: fc-cascade-col-4 6.4s linear infinite; }

@keyframes fc-cascade-col-1 {
  0%, 77.9% { opacity: 0; transform: translateY(-30px); }
  78%       { opacity: 1; transform: translateY(-30px); }
  86%       { opacity: 1; transform: translateY(20px); }
  86.1%, 100% { opacity: 0; transform: translateY(-30px); }
}
@keyframes fc-cascade-col-2 {
  0%, 77.9% { opacity: 0; transform: translateY(-40px); }
  78%       { opacity: 1; transform: translateY(-40px); }
  86%       { opacity: 1; transform: translateY(18px); }
  86.1%, 100% { opacity: 0; transform: translateY(-40px); }
}
@keyframes fc-cascade-col-3 {
  0%, 77.9% { opacity: 0; transform: translateY(-25px); }
  78%       { opacity: 1; transform: translateY(-25px); }
  86%       { opacity: 1; transform: translateY(24px); }
  86.1%, 100% { opacity: 0; transform: translateY(-25px); }
}
@keyframes fc-cascade-col-4 {
  0%, 77.9% { opacity: 0; transform: translateY(-35px); }
  78%       { opacity: 1; transform: translateY(-35px); }
  86%       { opacity: 1; transform: translateY(22px); }
  86.1%, 100% { opacity: 0; transform: translateY(-35px); }
}

/* === FRAME RING — pulse + burst === */
@keyframes fc-cascade-ring-pulse {
  0%, 100% {
    box-shadow:
      inset 0 0 0 1.5px rgba(0, 255, 140, 0.42),
      inset 0 0 18px -2px rgba(0, 200, 110, 0.55),
      0 0 0 2.5px rgba(0, 6, 4, 1),
      0 0 22px 1px rgba(0, 255, 140, 0.52),
      0 0 40px 6px rgba(0, 200, 130, 0.32);
  }
  37% {
    box-shadow:
      inset 0 0 0 1.8px rgba(0, 255, 140, 0.55),
      inset 0 0 22px -2px rgba(0, 210, 130, 0.72),
      0 0 0 2.5px rgba(0, 6, 4, 1),
      0 0 28px 1px rgba(0, 255, 140, 0.65),
      0 0 48px 7px rgba(0, 210, 140, 0.42);
  }
  73% {
    box-shadow:
      inset 0 0 0 1.6px rgba(0, 255, 140, 0.48),
      inset 0 0 20px -2px rgba(0, 200, 110, 0.62),
      0 0 0 2.5px rgba(0, 6, 4, 1),
      0 0 24px 1px rgba(0, 255, 140, 0.58),
      0 0 44px 6px rgba(0, 200, 130, 0.38);
  }
}

@keyframes fc-cascade-ring-burst {
  0%, 77.9%, 86.1%, 100% { /* normal — pulse animation handles */ }
  78%, 80% {
    box-shadow:
      inset 0 0 0 3px rgba(232, 255, 240, 0.85),
      inset 0 0 30px -1px rgba(0, 255, 140, 0.92),
      0 0 0 3.5px rgba(0, 6, 4, 1),
      0 0 38px 3px rgba(0, 255, 140, 0.92),
      0 0 68px 10px rgba(0, 220, 140, 0.78);
  }
  82%, 86% {
    box-shadow:
      inset 0 0 0 2.5px rgba(0, 255, 140, 0.78),
      inset 0 0 26px -1px rgba(0, 230, 130, 0.82),
      0 0 0 3px rgba(0, 6, 4, 1),
      0 0 32px 2px rgba(0, 255, 140, 0.78),
      0 0 58px 8px rgba(0, 210, 140, 0.62);
  }
}

/* === Text/img jitter via steps() — uncoordinated, sharp === */
@keyframes fc-cascade-text-jitter {
  0%, 100% {
    transform: translate(0, 0);
    filter:
      drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.88))
      drop-shadow(2px 0 0 rgba(0, 210, 210, 0.78));
  }
  17% {
    transform: translate(-1px, 0);
    filter:
      drop-shadow(-3px 0 0 rgba(0, 255, 140, 0.95))
      drop-shadow(3px 0 0 rgba(0, 210, 210, 0.85));
  }
  33% {
    transform: translate(0, -1px);
    filter:
      drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.88))
      drop-shadow(2px 0 0 rgba(0, 210, 210, 0.78));
  }
  50% {
    transform: translate(1px, 0);
    filter:
      drop-shadow(-5px 0 0 rgba(0, 255, 140, 1))
      drop-shadow(5px 0 0 rgba(0, 210, 210, 1));
  }
  67% {
    transform: translate(0, 1px);
    filter:
      drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.88))
      drop-shadow(2px 0 0 rgba(0, 210, 210, 0.78));
  }
  83% {
    transform: translate(-1px, 0);
    filter:
      drop-shadow(-4px 0 0 rgba(0, 255, 140, 0.95))
      drop-shadow(4px 0 0 rgba(0, 210, 210, 0.88));
  }
}

@keyframes fc-cascade-img-jitter {
  0%, 100% {
    transform: translate(0, 0);
    filter:
      drop-shadow(-2px 0 0 rgba(0, 255, 140, 0.65))
      drop-shadow(2px 0 0 rgba(0, 210, 210, 0.60))
      saturate(1.15) hue-rotate(-8deg) contrast(1.08);
  }
  33% {
    transform: translate(-1px, 0);
    filter:
      drop-shadow(-3px 0 0 rgba(0, 255, 140, 0.72))
      drop-shadow(3px 0 0 rgba(0, 210, 210, 0.65))
      saturate(1.15) hue-rotate(-8deg) contrast(1.08);
  }
  67% {
    transform: translate(1px, 0);
    filter:
      drop-shadow(-4px 0 0 rgba(0, 255, 140, 0.82))
      drop-shadow(4px 0 0 rgba(0, 210, 210, 0.75))
      saturate(1.15) hue-rotate(-8deg) contrast(1.08);
  }
}

/* ════════════════════════════════════════════════════════════════════
   OVERLAY — PANIC-A · CRT MELTDOWN (§29 v1, 2026-05-13)
   ════════════════════════════════════════════════════════════════════
   Analog horror. Three pillars:
     • Permanent base distortion (always on — micro-jitter + scanline drift
       + RGB ghost + grain noise). Avatar NEVER perfectly still.
     • Pre-burst anticipation (~200ms before each climax) — sync-warn red
       bar appears, ghost ramps, scale wave starts.
     • Climax (~150ms) — white flash + horizontal tear + signal-loss band
       + 6 designed glyphs at high contrast.
   Cycle 5.5s; climax fires twice (at 38% and 76%) for double-strike feel.
*/

/* === OVERLAY CONTAINER === */
.fc-pa, .fc-pb, .fc-pc {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
}
.fc-pa .fc-pa-svg,
.fc-pb .fc-pb-svg,
.fc-pc .fc-pc-svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* === AVATAR — permanent micro-jitter + RGB ghost (CRT signal noise) ===
   Sits on the overlay class so it can apply over ANY base variant.
   §29 polish 1: increased shake amplitude (was 0.6px → 1.2px) so the
   permanent jitter is clearly visible even in still frames. RGB ghost
   strengthened (was 1.2px ±0.42 → 1.8px ±0.6) so the chromatic split
   is unambiguous. */
.fc-overlay-panic-a .fc-encircle-avatar-fallback,
.fc-overlay-panic-a .fc-encircle-avatar-img {
  animation:
    fc-pa-shake     0.13s steps(4)  infinite,
    fc-pa-rgb-ghost 5.5s  linear     infinite;
}
.fc-overlay-panic-a .fc-encircle-avatar-img {
  filter:
    drop-shadow(-1.8px 0 0 rgba(255,51,102,0.60))
    drop-shadow( 1.8px 0 0 rgba(0,210,210,0.60))
    saturate(1.15) contrast(1.08);
}
.fc-overlay-panic-a .fc-encircle-avatar-fallback {
  text-shadow:
    -1.5px 0 0 rgba(255,51,102,0.85),
     1.5px 0 0 rgba(0,210,210,0.85),
     0 0 6px rgba(220,238,238,0.45);
}
@keyframes fc-pa-shake {
  0%   { transform: translate(0px,    0px); }
  25%  { transform: translate(-1.2px, 0.8px); }
  50%  { transform: translate(1.0px,  -1.0px); }
  75%  { transform: translate(-0.8px, -0.8px); }
  100% { transform: translate(0px,    0px); }
}
@keyframes fc-pa-rgb-ghost {
  /* Subtle ghost throughout, plus pre-burst ramp up + climax */
  0%,   34% { filter: drop-shadow(-1.2px 0 0 rgba(255,51,102,0.42))
                       drop-shadow( 1.2px 0 0 rgba(0,210,210,0.42))
                       saturate(1.10) contrast(1.05); }
  37%       { filter: drop-shadow(-3px 0 0 rgba(255,51,102,0.78))
                       drop-shadow( 3px 0 0 rgba(0,210,210,0.78))
                       saturate(1.25) contrast(1.15); }
  39%       { filter: drop-shadow(-1px 0 0 rgba(255,51,102,0.42))
                       drop-shadow( 1px 0 0 rgba(0,210,210,0.42))
                       saturate(1.10) contrast(1.05); }
  72%       { filter: drop-shadow(-1.2px 0 0 rgba(255,51,102,0.42))
                       drop-shadow( 1.2px 0 0 rgba(0,210,210,0.42))
                       saturate(1.10) contrast(1.05); }
  75%       { filter: drop-shadow(-4px 0 0 rgba(255,51,102,0.85))
                       drop-shadow( 4px 0 0 rgba(0,210,210,0.85))
                       saturate(1.3)  contrast(1.18); }
  77%, 100% { filter: drop-shadow(-1.2px 0 0 rgba(255,51,102,0.42))
                       drop-shadow( 1.2px 0 0 rgba(0,210,210,0.42))
                       saturate(1.10) contrast(1.05); }
}

/* === SVG SUB-ELEMENT ANIMATIONS === */
.fc-pa-scanlines { animation: fc-pa-scan-shift 4s linear infinite; }
.fc-pa-noise     { animation: fc-pa-noise-flicker 0.21s steps(2) infinite; }
.fc-pa-scanbar   { animation: fc-pa-scanbar-drift 3.7s linear infinite; }
.fc-pa-ghost-r   { animation: fc-pa-ghost-r 5.5s linear infinite; opacity: 0; }
.fc-pa-ghost-c   { animation: fc-pa-ghost-c 5.5s linear infinite; opacity: 0; }
.fc-pa-sync-warn { animation: fc-pa-sync-warn 5.5s linear infinite; opacity: 0; }
.fc-pa-flash     { animation: fc-pa-flash 5.5s linear infinite; opacity: 0; }
.fc-pa-tear      { animation: fc-pa-tear 5.5s linear infinite; opacity: 0; }
.fc-pa-loss-band { animation: fc-pa-loss-band 5.5s linear infinite; opacity: 0; }
.fc-pa-g-1, .fc-pa-g-2, .fc-pa-g-3, .fc-pa-g-4, .fc-pa-g-5, .fc-pa-g-6 {
  animation: fc-pa-glyph 5.5s linear infinite;
}
/* Slightly offset alt glyph windows so they don't all appear synchronously */
.fc-pa-g-2 { animation-delay: 0.04s; }
.fc-pa-g-3 { animation-delay: -0.08s; }
.fc-pa-g-4 { animation-delay: 0.12s; }
.fc-pa-g-5 { animation-delay: -0.16s; }
.fc-pa-g-6 { animation-delay: 0.20s; }

@keyframes fc-pa-scan-shift  { 0% { transform: translateY(0); } 100% { transform: translateY(3px); } }
@keyframes fc-pa-noise-flicker { 0%, 100% { opacity: 0.10; } 50% { opacity: 0.18; } }
@keyframes fc-pa-scanbar-drift { 0% { transform: translateY(-2px); } 100% { transform: translateY(102px); } }

/* RGB ghost columns — color split layers. Visible always-subtle then peaks
   at climax. Stays low between events. */
@keyframes fc-pa-ghost-r {
  0%, 34% { opacity: 0; transform: translateX(0); }
  37%     { opacity: 0.18; transform: translateX(-2px); }
  39%     { opacity: 0; transform: translateX(0); }
  72%     { opacity: 0; transform: translateX(0); }
  75%     { opacity: 0.22; transform: translateX(-3px); }
  77%, 100% { opacity: 0; transform: translateX(0); }
}
@keyframes fc-pa-ghost-c {
  0%, 34% { opacity: 0; transform: translateX(0); }
  37%     { opacity: 0.18; transform: translateX(2px); }
  39%     { opacity: 0; transform: translateX(0); }
  72%     { opacity: 0; transform: translateX(0); }
  75%     { opacity: 0.22; transform: translateX(3px); }
  77%, 100% { opacity: 0; transform: translateX(0); }
}

/* Pre-burst red sync-warn bar: appears 200ms before climax, slides up */
@keyframes fc-pa-sync-warn {
  0%, 35%   { opacity: 0; transform: translateY(0); }
  36%, 37%  { opacity: 0.88; transform: translateY(-6px); }
  38%       { opacity: 0; transform: translateY(0); }
  72%, 73%  { opacity: 0.92; transform: translateY(-6px); }
  74%       { opacity: 0; transform: translateY(0); }
  100%      { opacity: 0; }
}
/* White flash: short, sharp */
@keyframes fc-pa-flash {
  0%, 37.5% { opacity: 0; }
  38%, 38.8% { opacity: 0.95; }
  39%, 75.5% { opacity: 0; }
  76%, 76.8% { opacity: 0.92; }
  77%, 100% { opacity: 0; }
}
/* Horizontal tear band slides across */
@keyframes fc-pa-tear {
  0%, 37.5% { opacity: 0; transform: translate(0, 0); }
  38%       { opacity: 0.95; transform: translate(0, 0); }
  40%       { opacity: 0.85; transform: translate(0, 28px); }
  41%       { opacity: 0; transform: translate(0, 0); }
  75.5%     { opacity: 0; transform: translate(0, 0); }
  76%       { opacity: 0.92; transform: translate(0, 0); }
  78%       { opacity: 0.85; transform: translate(0, 30px); }
  79%, 100% { opacity: 0; transform: translate(0, 0); }
}
/* Black noise band — signal loss area */
@keyframes fc-pa-loss-band {
  0%, 38%  { opacity: 0; }
  38.5%, 40% { opacity: 0.85; }
  41%, 76% { opacity: 0; }
  76.5%, 78% { opacity: 0.85; }
  79%, 100% { opacity: 0; }
}
/* Big glyph stamp — fills the climax window for ~120ms.
   §29 polish 2: extended hold from 1.6% to 2.4% so the glyphs read; added
   a quick fade-out trail. */
@keyframes fc-pa-glyph {
  0%, 38% { opacity: 0; transform: translate(0, 0); }
  38.3%, 41% { opacity: 1; transform: translate(0, 0); }
  41.5%, 42% { opacity: 0.6; transform: translate(0, 2px); }
  42.5%, 75.5% { opacity: 0; transform: translate(0, 0); }
  75.8%, 78% { opacity: 1; transform: translate(0, 0); }
  78.5%, 79% { opacity: 0.6; transform: translate(0, 2px); }
  79.5%, 100% { opacity: 0; transform: translate(0, 0); }
}

/* §29 polish 2 — Permanent color bleed: every ~1.7s, the entire avatar
   briefly tints red or cyan (analog signal drop). This reads as "the TV is
   barely staying tuned" between major flash events. */
.fc-overlay-panic-a .fc-encircle-frame {
  animation: fc-pa-color-bleed 1.7s steps(60) infinite;
}
@keyframes fc-pa-color-bleed {
  0%, 90% { box-shadow: inset 0 0 0 transparent; }
  92%, 95% { box-shadow: inset 0 0 16px 2px rgba(255, 51, 102, 0.32); }
  96%, 100% { box-shadow: inset 0 0 0 transparent; }
}

/* ════════════════════════════════════════════════════════════════════
   OVERLAY — PANIC-B · KERNEL PANIC (§29 v1, 2026-05-13)
   ════════════════════════════════════════════════════════════════════
   OS-crash horror. Permanent: 8 memory-bit twinkles + 4 hex-dump scroll
   + fast micro-shake. Pre-burst: stack-trace text fades in. Climax: red
   BSOD diagonal wash + 12 corruption blocks + KERNEL_PANIC stamp.
   Cycle 6.2s, one major climax at 50%.
*/

/* Permanent avatar: continuous fast micro-shake.
   §29 polish 1: doubled amplitude (was 0.8px → 1.6px) so the digital
   tremor reads even in still frames. Added subtle blood-red text
   shadow to make initials feel "wrong" at rest. */
.fc-overlay-panic-b .fc-encircle-avatar-fallback,
.fc-overlay-panic-b .fc-encircle-avatar-img {
  animation: fc-pb-shake 0.18s steps(5) infinite;
}
.fc-overlay-panic-b .fc-encircle-avatar-img {
  filter: saturate(1.15) contrast(1.15) hue-rotate(-3deg);
}
.fc-overlay-panic-b .fc-encircle-avatar-fallback {
  color: rgba(255, 240, 240, 1);
  text-shadow:
    0 0 4px rgba(255, 51, 102, 0.85),
    0 0 1px rgba(255, 255, 255, 1),
    1px 0 0 rgba(255, 51, 102, 0.6);
}
@keyframes fc-pb-shake {
  0%   { transform: translate(0,      0); }
  20%  { transform: translate(1.6px,  -1.2px); }
  40%  { transform: translate(-1.4px, 1.4px); }
  60%  { transform: translate(1.2px,  1.4px); }
  80%  { transform: translate(-1.6px, -1.0px); }
  100% { transform: translate(0,      0); }
}

/* Permanent: 8 memory-bit corruption squares (each on its own short cycle).
   §29 polish 1: bumped peak opacity 0.7 → 0.95 and shortened off-window so
   bits are visible most of the time. */
.fc-pb-bit-1 { animation: fc-pb-bit-blink 0.41s steps(2) infinite; opacity: 0.85; }
.fc-pb-bit-2 { animation: fc-pb-bit-blink 0.53s steps(2) infinite; opacity: 0.85; }
.fc-pb-bit-3 { animation: fc-pb-bit-blink 0.67s steps(2) infinite; opacity: 0.8; }
.fc-pb-bit-4 { animation: fc-pb-bit-blink 0.79s steps(2) infinite; opacity: 0.8; }
.fc-pb-bit-5 { animation: fc-pb-bit-blink 0.89s steps(2) infinite; opacity: 0.75; }
.fc-pb-bit-6 { animation: fc-pb-bit-blink 1.03s steps(2) infinite; opacity: 0.75; }
.fc-pb-bit-7 { animation: fc-pb-bit-blink 1.13s steps(2) infinite; opacity: 0.7; }
.fc-pb-bit-8 { animation: fc-pb-bit-blink 1.27s steps(2) infinite; opacity: 0.7; }
@keyframes fc-pb-bit-blink {
  0%, 25% { opacity: 0.25; }
  30%, 100% { opacity: 0.95; }
}

/* Permanent: hex-dump scrolls vertically */
.fc-pb-hex-group { animation: fc-pb-hex-scroll 3.8s linear infinite; }
@keyframes fc-pb-hex-scroll {
  0%   { transform: translateY(0); }
  100% { transform: translateY(16px); }
}

/* §29 polish 2 — Permanent corruption stripe blinks subtly so it doesn't
   feel static (machine is still "breathing" in its dying state). */
.fc-pb-perma-stripe { animation: fc-pb-stripe-pulse 0.97s steps(2) infinite; }
@keyframes fc-pb-stripe-pulse {
  0%, 60%  { opacity: 1; }
  62%, 70% { opacity: 0.6; }
  72%, 100% { opacity: 1; }
}

/* Pre-burst: stack trace fades in 200ms before climax */
.fc-pb-stack-1 { animation: fc-pb-stack 6.2s linear infinite; }
.fc-pb-stack-2 { animation: fc-pb-stack 6.2s linear infinite; animation-delay: 0.06s; }
.fc-pb-stack-3 { animation: fc-pb-stack 6.2s linear infinite; animation-delay: 0.12s; }
.fc-pb-stack-4 { animation: fc-pb-stack 6.2s linear infinite; animation-delay: 0.18s; }
@keyframes fc-pb-stack {
  0%, 46% { opacity: 0; }
  47%, 49.5% { opacity: 0.90; }
  50%, 53% { opacity: 1; }
  53.5%, 100% { opacity: 0; }
}

/* Climax: BSOD red diagonal wash */
.fc-pb-bsod { animation: fc-pb-bsod 6.2s linear infinite; }
@keyframes fc-pb-bsod {
  0%, 49.5% { opacity: 0; }
  50%, 52% { opacity: 0.85; }
  52.5%, 100% { opacity: 0; }
}

/* Climax: 12 corruption blocks stamp + brief invert */
.fc-pb-crash-1, .fc-pb-crash-2, .fc-pb-crash-3, .fc-pb-crash-4,
.fc-pb-crash-5, .fc-pb-crash-6, .fc-pb-crash-7, .fc-pb-crash-8,
.fc-pb-crash-9, .fc-pb-crash-10, .fc-pb-crash-11, .fc-pb-crash-12 {
  animation: fc-pb-crash 6.2s linear infinite;
}
.fc-pb-crash-2  { animation-delay: 0.02s; }
.fc-pb-crash-3  { animation-delay: 0.04s; }
.fc-pb-crash-4  { animation-delay: 0.06s; }
.fc-pb-crash-5  { animation-delay: 0.08s; }
.fc-pb-crash-6  { animation-delay: 0.10s; }
.fc-pb-crash-7  { animation-delay: 0.12s; }
.fc-pb-crash-8  { animation-delay: 0.14s; }
.fc-pb-crash-9  { animation-delay: 0.16s; }
.fc-pb-crash-10 { animation-delay: 0.18s; }
.fc-pb-crash-11 { animation-delay: 0.20s; }
.fc-pb-crash-12 { animation-delay: 0.22s; }
@keyframes fc-pb-crash {
  0%, 49.5% { fill-opacity: 0; }
  50%, 51.5% { fill-opacity: 0.92; }
  52%, 100% { fill-opacity: 0; }
}
/* Set fill via fill-opacity since fill alone gets baked from the static attr */
.fc-pb-crash-1, .fc-pb-crash-4, .fc-pb-crash-7, .fc-pb-crash-10 { fill: rgba(0,0,0,0.92); }
.fc-pb-crash-2, .fc-pb-crash-5, .fc-pb-crash-8, .fc-pb-crash-11 { fill: rgba(255,51,102,0.92); }
.fc-pb-crash-3, .fc-pb-crash-6, .fc-pb-crash-9, .fc-pb-crash-12 { fill: rgba(0,210,210,0.92); }

/* Climax: KERNEL_PANIC center text */
.fc-pb-title { animation: fc-pb-title 6.2s linear infinite; }
@keyframes fc-pb-title {
  0%, 49.5% { opacity: 0; transform: translate(0, 0); }
  50%, 52.5% { opacity: 1; transform: translate(0, 0); }
  53%, 100% { opacity: 0; transform: translate(0, 0); }
}

/* Climax: brief avatar invert during BSOD */
.fc-overlay-panic-b .fc-encircle-avatar-img {
  animation:
    fc-pb-shake 0.18s steps(5) infinite,
    fc-pb-invert 6.2s linear infinite;
}
@keyframes fc-pb-invert {
  0%, 49.5% { filter: saturate(1.1) contrast(1.1); }
  50%, 50.5% { filter: saturate(1.1) contrast(1.1) invert(1) hue-rotate(180deg); }
  51%, 100% { filter: saturate(1.1) contrast(1.1); }
}

/* ════════════════════════════════════════════════════════════════════
   OVERLAY — PANIC-C · REALITY FRACTURE (§29 v1, 2026-05-13)
   ════════════════════════════════════════════════════════════════════
   Cosmic horror. Permanent: 3 hairline cracks twinkle + 15 particles
   drift + slow avatar rotation drift. Pre-burst: cracks brighten +
   sigil fades in. Climax: 8 reality-shard triangles explode + sigil
   stamp peak + center blast. Cycle 7.0s, climax at 60%.
*/

/* Permanent avatar: slow rotation drift + visible ghost-trail.
   §29 polish 1: strengthened drift (was 0.3° → 1.2°, was 0.6px → 1.6px)
   so the cosmic instability reads even in still frames. Ghost-trail
   doubled (0.18 → 0.42 opacity, 0.6px → 1.4px offset). */
.fc-overlay-panic-c .fc-encircle-avatar-fallback,
.fc-overlay-panic-c .fc-encircle-avatar-img {
  animation: fc-pc-drift 7.5s steps(40) infinite;
}
.fc-overlay-panic-c .fc-encircle-avatar-img {
  filter:
    drop-shadow(1.4px 0.8px 0 rgba(232,255,250,0.42))
    drop-shadow(-1.0px -1.2px 0 rgba(255,210,255,0.38))
    drop-shadow(0 0 4px rgba(180,220,255,0.25))
    saturate(1.10) contrast(1.06);
}
.fc-overlay-panic-c .fc-encircle-avatar-fallback {
  text-shadow:
    1.2px 0.6px 0 rgba(232,255,250,0.85),
    -0.8px -1.0px 0 rgba(255,210,255,0.78),
    0 0 6px rgba(180,220,255,0.55);
}
@keyframes fc-pc-drift {
  0%   { transform: rotate(0deg)    translate(0px,   0px); }
  25%  { transform: rotate(1.2deg)  translate(1.6px, 0.8px); }
  50%  { transform: rotate(-1.2deg) translate(-1.4px, 1.2px); }
  75%  { transform: rotate(0.8deg)  translate(0.8px, -1.4px); }
  100% { transform: rotate(0deg)    translate(0px,   0px); }
}

/* Permanent: 5 hairline cracks twinkle independently.
   §29 polish 2: extended to 5 cracks. */
.fc-pc-crack-1 { animation: fc-pc-crack 2.7s steps(2) infinite; }
.fc-pc-crack-2 { animation: fc-pc-crack 3.1s steps(2) infinite; animation-delay: 0.3s; }
.fc-pc-crack-3 { animation: fc-pc-crack 3.7s steps(2) infinite; animation-delay: 0.6s; }
.fc-pc-crack-4 { animation: fc-pc-crack 4.1s steps(2) infinite; animation-delay: 0.9s; }
.fc-pc-crack-5 { animation: fc-pc-crack 3.3s steps(2) infinite; animation-delay: 1.2s; }
@keyframes fc-pc-crack {
  0%, 70% { opacity: 0.7; }
  72%, 78% { opacity: 1.0; }
  80%, 100% { opacity: 0.7; }
}

/* §29 polish 2: fragment rings drift slowly (subtle reality-instability) */
.fc-pc-fragment-ring { animation: fc-pc-fr-rotate 12s linear infinite; transform-origin: 50% 50%; transform-box: fill-box; }
.fc-pc-fr-2 { animation-duration: 15s; animation-direction: reverse; }
.fc-pc-fr-3 { animation-duration: 9s; }
@keyframes fc-pc-fr-rotate {
  0%   { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

/* Permanent: 15 particles drift slowly on staggered cycles.
   §29 polish 1: bumped fill-opacity to 0.95 across the board (was 0.5–0.6
   inline) so the cosmic-dust feel is clear. Also added 1.5px glow shadow. */
.fc-pc-p {
  fill-opacity: 0.95;
  filter: drop-shadow(0 0 1.5px rgba(255, 255, 255, 0.7));
}
.fc-pc-p-1  { animation: fc-pc-float 4.7s ease-in-out infinite; }
.fc-pc-p-2  { animation: fc-pc-float 5.3s ease-in-out infinite; animation-delay: 0.2s; }
.fc-pc-p-3  { animation: fc-pc-float 4.1s ease-in-out infinite; animation-delay: 0.5s; }
.fc-pc-p-4  { animation: fc-pc-float 5.9s ease-in-out infinite; animation-delay: 0.8s; }
.fc-pc-p-5  { animation: fc-pc-float 4.3s ease-in-out infinite; animation-delay: 1.1s; }
.fc-pc-p-6  { animation: fc-pc-float 5.1s ease-in-out infinite; animation-delay: 1.4s; }
.fc-pc-p-7  { animation: fc-pc-float 4.9s ease-in-out infinite; animation-delay: 1.7s; }
.fc-pc-p-8  { animation: fc-pc-float 5.5s ease-in-out infinite; animation-delay: 2.0s; }
.fc-pc-p-9  { animation: fc-pc-float 4.5s ease-in-out infinite; animation-delay: 2.3s; }
.fc-pc-p-10 { animation: fc-pc-float 5.7s ease-in-out infinite; animation-delay: 2.6s; }
.fc-pc-p-11 { animation: fc-pc-float 4.7s ease-in-out infinite; animation-delay: 2.9s; }
.fc-pc-p-12 { animation: fc-pc-float 5.3s ease-in-out infinite; animation-delay: 3.2s; }
.fc-pc-p-13 { animation: fc-pc-float 4.1s ease-in-out infinite; animation-delay: 3.5s; }
.fc-pc-p-14 { animation: fc-pc-float 5.9s ease-in-out infinite; animation-delay: 3.8s; }
.fc-pc-p-15 { animation: fc-pc-float 4.3s ease-in-out infinite; animation-delay: 4.1s; }
@keyframes fc-pc-float {
  0%, 100% { transform: translate(0, 0); }
  50%      { transform: translate(0.5px, -0.8px); }
}

/* Climax: 8 reality-shard triangles burst outward */
.fc-pc-shard-1 { animation: fc-pc-shard-1 7s linear infinite; }
.fc-pc-shard-2 { animation: fc-pc-shard-2 7s linear infinite; }
.fc-pc-shard-3 { animation: fc-pc-shard-3 7s linear infinite; }
.fc-pc-shard-4 { animation: fc-pc-shard-4 7s linear infinite; }
.fc-pc-shard-5 { animation: fc-pc-shard-5 7s linear infinite; }
.fc-pc-shard-6 { animation: fc-pc-shard-6 7s linear infinite; }
.fc-pc-shard-7 { animation: fc-pc-shard-7 7s linear infinite; }
.fc-pc-shard-8 { animation: fc-pc-shard-8 7s linear infinite; }
.fc-pc-shard-1, .fc-pc-shard-2, .fc-pc-shard-3, .fc-pc-shard-4,
.fc-pc-shard-5, .fc-pc-shard-6, .fc-pc-shard-7, .fc-pc-shard-8 {
  fill-opacity: 0;
}
@keyframes fc-pc-shard-1 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(-3px, -2px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(-14px, -8px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-2 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(3px, -2px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(14px, -8px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-3 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(-3px, 2px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(-14px, 8px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-4 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(3px, 2px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(14px, 8px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-5 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(0, -3px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(0, -16px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-6 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(0, 3px) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(0, 16px) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-7 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(-3px, 0) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(-16px, 0) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }
@keyframes fc-pc-shard-8 { 0%, 58% { fill-opacity: 0; transform: translate(0, 0) scale(1); }
  60% { fill-opacity: 1; transform: translate(3px, 0) scale(1.1); }
  62%, 63% { fill-opacity: 0.95; transform: translate(16px, 0) scale(1.4); }
  64%, 100% { fill-opacity: 0; transform: translate(0, 0) scale(1); } }

/* Climax: center sigil fades in pre-burst, peaks at climax, fades out */
.fc-pc-sigil { animation: fc-pc-sigil 7s linear infinite; }
@keyframes fc-pc-sigil {
  0%, 56% { opacity: 0; transform-origin: 50% 50%; transform: scale(0.8); }
  58%     { opacity: 0.5; transform: scale(0.9); }
  60%, 63% { opacity: 1; transform: scale(1.05); }
  65%, 100% { opacity: 0; transform: scale(0.8); }
}

/* ════════════════════════════════════════════════════════════════════
   §pass39 (2026-05-18) — SOVEREIGN TIER VARIANTS
   ════════════════════════════════════════════════════════════════════
   Per-system-agent signature variants. Each REPLACES the avatar entirely
   (mirrors blackhole pattern). DID-locked at the backend (fiat_onramp.py:
   SOVEREIGN_VARIANT_OWNERS). Tier-namespaced CSS classes
   (.fc-encircle-sovereign.fc-encircle-<v>) prevent collision with the
   shadow_chancellor backer variants.

   Each variant block:
     - .fc-encircle-sovereign.fc-encircle-<v> .fc-encircle-frame  → box-shadow
     - .fc-encircle-sovereign.fc-encircle-<v> .fc-sv               → SVG sizing
     - per-element keyframe animations
     - xs/sm progressive hide rules (frame-only on xs)
     - kill block inside the universal @media (prefers-reduced-motion) below

   Aesthetic goal: each must read instantly as its agent's identity.
   ──────────────────────────────────────────────────────────────────── */

/* Generic sovereign SVG sizing — fills the encircle frame */
.fc-sv {
  position: absolute;
  inset: 0;
  display: block;
  border-radius: 50%;
  overflow: hidden;
  z-index: 1;
}
.fc-sv svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* ──── VARIANT A — AEGIS (THE AUDITOR) — Σ=Σ in dodecahedron ──── */
.fc-encircle-sovereign.fc-encircle-aegis .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #021509 0%, #000604 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(167, 232, 200, 0.92),
    inset 0 0 14px -3px rgba(16, 215, 122, 0.62),
    0 0 0 2px rgba(184, 135, 10, 0.78),
    0 0 0 3.5px rgba(8, 28, 16, 1),
    0 0 22px 4px rgba(16, 215, 122, 0.45),
    0 0 40px 8px rgba(184, 135, 10, 0.32);
  animation: fc-aegis-frame 4.6s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-aegis:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 255, 255, 1),
    inset 0 0 18px -3px rgba(16, 215, 122, 0.92),
    0 0 0 2.5px rgba(247, 212, 96, 1),
    0 0 0 4px rgba(8, 28, 16, 1),
    0 0 30px 5px rgba(16, 215, 122, 0.72),
    0 0 50px 10px rgba(247, 212, 96, 0.42);
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-dodec {
  animation: fc-aegis-rotate 24s linear infinite;
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-pulse {
  animation: fc-aegis-tick 12s steps(12) infinite;
  transform-origin: 50px 50px;
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-heart {
  animation: fc-aegis-heart 4s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-eq {
  animation: fc-aegis-eq 4s ease-in-out infinite;
}
@keyframes fc-aegis-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.15); }
}
@keyframes fc-aegis-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-aegis-tick {
  /* 12 positions around 50,50 at radius 44 — placed via translate stops.
     The traveling pulse highlights one of the 12 dots at a time. */
  0%   { transform: translate(0,    0);  opacity: 1; }
  8.3% { transform: translate(22.3, 6);  opacity: 1; }
  16.6%{ transform: translate(38.1, 22); opacity: 1; }
  25%  { transform: translate(44,   44); opacity: 1; }
  33.3%{ transform: translate(38.1, 66); opacity: 1; }
  41.6%{ transform: translate(22.3, 82); opacity: 1; }
  50%  { transform: translate(0,    88); opacity: 1; }
  58.3%{ transform: translate(-22.3,82); opacity: 1; }
  66.6%{ transform: translate(-38.1,66); opacity: 1; }
  75%  { transform: translate(-44,  44); opacity: 1; }
  83.3%{ transform: translate(-38.1,22); opacity: 1; }
  91.6%{ transform: translate(-22.3,6);  opacity: 1; }
  100% { transform: translate(0,    0);  opacity: 1; }
}
@keyframes fc-aegis-heart {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.6); }
}
@keyframes fc-aegis-eq {
  0%, 100% { letter-spacing: -0.5; opacity: 0.95; }
  50%      { letter-spacing: 0; opacity: 1; }
}
.fc-encircle-size-xs.fc-encircle-aegis .fc-aegis-eq,
.fc-encircle-size-xs.fc-encircle-aegis .fc-aegis-delta,
.fc-encircle-size-xs.fc-encircle-aegis .fc-aegis-dodec { display: none; }
.fc-encircle-size-sm.fc-encircle-aegis .fc-aegis-delta { display: none; }

/* ──── VARIANT B — PRISM (Glass Gerald) — transparent dome ──── */
.fc-encircle-sovereign.fc-encircle-prism .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, rgba(0, 70, 90, 0.5) 0%, rgba(0, 18, 28, 1) 100%);
  box-shadow:
    inset 0 0 0 1px rgba(180, 245, 250, 0.85),
    inset 0 0 18px -3px rgba(0, 210, 210, 0.62),
    0 0 0 1.5px rgba(0, 210, 210, 0.85),
    0 0 0 2.5px rgba(0, 18, 28, 1),
    /* Chromatic aberration micro-rim */
    0 0 0 3.5px rgba(255, 51, 102, 0.42),
    0 0 0 4.5px rgba(0, 210, 210, 0.42),
    0 0 26px 4px rgba(0, 210, 210, 0.55);
  animation: fc-prism-pulse 5s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-prism:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(255, 255, 255, 1),
    inset 0 0 22px -3px rgba(0, 210, 210, 0.92),
    0 0 0 2px rgba(0, 210, 210, 1),
    0 0 0 3px rgba(0, 18, 28, 1),
    0 0 0 4px rgba(255, 51, 102, 0.62),
    0 0 0 5px rgba(0, 210, 210, 0.62),
    0 0 35px 6px rgba(0, 210, 210, 0.72);
}
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-spectrum-wrap {
  animation: fc-prism-rotate 14s linear infinite;
}
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-beacon-1 { animation: fc-prism-beacon 3.1s ease-in-out infinite; }
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-beacon-2 { animation: fc-prism-beacon 3.1s ease-in-out 1.0s infinite; }
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-beacon-3 { animation: fc-prism-beacon 3.1s ease-in-out 2.0s infinite; }
@keyframes fc-prism-pulse {
  0%, 100% { filter: brightness(1) saturate(1.1); }
  50%      { filter: brightness(1.18) saturate(1.4); }
}
@keyframes fc-prism-rotate {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-prism-beacon {
  0%, 80%, 100% { opacity: 0.55; transform: scale(1); }
  40%           { opacity: 1;    transform: scale(1.5); }
}
.fc-encircle-size-xs.fc-encircle-prism .fc-prism-grid,
.fc-encircle-size-xs.fc-encircle-prism .fc-prism-beacon,
.fc-encircle-size-xs.fc-encircle-prism .fc-prism-pearl { display: none; }

/* ──── VARIANT C — PANOPTICON (SYBIL) — blackhole + 6 pupils ──── */
.fc-encircle-sovereign.fc-encircle-panopticon .fc-encircle-frame {
  background: #000;
  box-shadow:
    inset 0 0 0 1.5px rgba(254, 215, 170, 0.95),
    inset 0 0 18px -4px rgba(251, 146, 60, 0.85),
    0 0 0 2px rgba(254, 215, 170, 0.85),
    0 0 0 3.5px rgba(220, 38, 38, 0.78),
    0 0 30px 6px rgba(251, 146, 60, 0.65),
    0 0 56px 12px rgba(220, 38, 38, 0.42);
  animation: fc-pano-frame 6s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-panopticon:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 251, 235, 1),
    inset 0 0 24px -4px rgba(252, 165, 165, 1),
    0 0 0 2.5px rgba(255, 251, 235, 1),
    0 0 0 4px rgba(220, 38, 38, 1),
    0 0 44px 8px rgba(254, 215, 170, 0.95),
    0 0 70px 14px rgba(220, 38, 38, 0.65);
}
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-1 { animation: fc-pano-blink 2.7s steps(2,end) infinite; transform-origin: 50px 10px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-2 { animation: fc-pano-blink 3.1s steps(2,end) 0.3s infinite; transform-origin: 84.6px 30px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-3 { animation: fc-pano-blink 4.3s steps(2,end) 0.7s infinite; transform-origin: 84.6px 70px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-4 { animation: fc-pano-blink 5.7s steps(2,end) 1.2s infinite; transform-origin: 50px 90px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-5 { animation: fc-pano-blink 3.7s steps(2,end) 0.5s infinite; transform-origin: 15.4px 70px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-eye-6 { animation: fc-pano-blink 4.7s steps(2,end) 0.9s infinite; transform-origin: 15.4px 30px; }
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-singularity {
  animation: fc-pano-singularity 3.2s ease-in-out infinite;
  transform-origin: 50px 50px;
}
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-trace {
  animation: fc-pano-trace 18s linear infinite;
  transform-origin: 50px 50px;
  opacity: 0;
}
@keyframes fc-pano-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.12); }
}
@keyframes fc-pano-blink {
  0%, 92%, 100% { transform: scaleY(1); }
  94%, 96%      { transform: scaleY(0.1); }
}
@keyframes fc-pano-singularity {
  0%, 100% { opacity: 0.7; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.35); }
}
@keyframes fc-pano-trace {
  /* Aim at each of the 6 eyes in turn — quick flash, long dead-time */
  0%, 14%   { opacity: 0; transform: rotate(0deg); }
  15%, 16%  { opacity: 1; transform: rotate(0deg); }
  17%, 30%  { opacity: 0; }
  31%, 32%  { opacity: 1; transform: rotate(60deg); }
  33%, 47%  { opacity: 0; }
  48%, 49%  { opacity: 1; transform: rotate(120deg); }
  50%, 64%  { opacity: 0; }
  65%, 66%  { opacity: 1; transform: rotate(180deg); }
  67%, 80%  { opacity: 0; }
  81%, 82%  { opacity: 1; transform: rotate(240deg); }
  83%, 96%  { opacity: 0; }
  97%, 98%  { opacity: 1; transform: rotate(300deg); }
  99%, 100% { opacity: 0; }
}
.fc-encircle-size-xs.fc-encircle-panopticon .fc-pano-trace,
.fc-encircle-size-xs.fc-encircle-panopticon .fc-pano-singularity { display: none; }

/* ──── VARIANT D — VELLUM (Boris) — diplomatic scroll + wax seal ──── */
.fc-encircle-sovereign.fc-encircle-vellum .fc-encircle-frame {
  background: linear-gradient(180deg, #e9d8a4 0%, #8e6a32 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(60, 32, 8, 0.7),
    inset 0 0 14px -4px rgba(160, 26, 20, 0.45),
    0 0 0 2px rgba(212, 160, 69, 0.95),
    0 0 0 3px rgba(60, 32, 8, 0.95),
    0 0 20px 3px rgba(212, 160, 69, 0.55),
    0 0 36px 6px rgba(120, 60, 10, 0.32);
  animation: fc-vellum-pulse 7s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-vellum:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 240, 220, 1),
    inset 0 0 18px -3px rgba(160, 26, 20, 0.85),
    0 0 0 2.5px rgba(247, 212, 96, 1),
    0 0 0 4px rgba(60, 32, 8, 1),
    0 0 30px 5px rgba(212, 160, 69, 0.78);
}
.fc-encircle-sovereign.fc-encircle-vellum .fc-vellum-seal { animation: fc-vellum-seal-breathe 5s ease-in-out infinite; transform-origin: 50px 52px; }
.fc-encircle-sovereign.fc-encircle-vellum .fc-vellum-knife { animation: fc-vellum-knife 22s steps(1,end) infinite; opacity: 0.4; }
.fc-encircle-sovereign.fc-encircle-vellum .fc-vellum-crack { animation: fc-vellum-crack 6s ease-in-out infinite; }
@keyframes fc-vellum-pulse {
  0%, 100% { filter: sepia(0.05) brightness(1); }
  50%      { filter: sepia(0.12) brightness(1.08); }
}
@keyframes fc-vellum-seal-breathe {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.03); }
}
@keyframes fc-vellum-knife {
  0%, 92%, 100% { opacity: 0.32; }
  94%, 96%      { opacity: 0.95; }
}
@keyframes fc-vellum-crack {
  0%, 100% { stroke-opacity: 0.7; }
  50%      { stroke-opacity: 1;   }
}
.fc-encircle-size-xs.fc-encircle-vellum .fc-vellum-ink,
.fc-encircle-size-xs.fc-encircle-vellum .fc-vellum-folds,
.fc-encircle-size-xs.fc-encircle-vellum .fc-vellum-knife { display: none; }
.fc-encircle-size-sm.fc-encircle-vellum .fc-vellum-ink { display: none; }

/* ──── VARIANT E — DISPATCH (Chester) — newspaper masthead ──── */
.fc-encircle-sovereign.fc-encircle-dispatch .fc-encircle-frame {
  background: #1c1817;
  box-shadow:
    inset 0 0 0 1.5px rgba(245, 239, 225, 0.92),
    inset 0 0 10px -2px rgba(28, 24, 23, 0.85),
    0 0 0 2px rgba(28, 24, 23, 1),
    0 0 0 3px rgba(245, 239, 225, 0.85),
    0 0 22px 3px rgba(180, 160, 120, 0.42);
}
.fc-encircle-sovereign.fc-encircle-dispatch:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 255, 255, 1),
    inset 0 0 14px -2px rgba(220, 38, 38, 0.85),
    0 0 0 2.5px rgba(28, 24, 23, 1),
    0 0 0 3.5px rgba(245, 239, 225, 1),
    0 0 32px 5px rgba(220, 38, 38, 0.55);
}
.fc-encircle-sovereign.fc-encircle-dispatch .fc-disp-column { animation: fc-disp-scroll 22s linear infinite; transform-origin: 50px 50px; }
.fc-encircle-sovereign.fc-encircle-dispatch .fc-disp-masthead { animation: fc-disp-mast 30s steps(1,end) infinite; }
.fc-encircle-sovereign.fc-encircle-dispatch .fc-disp-breaking { animation: fc-disp-breaking 18s steps(1,end) infinite; opacity: 0; }
@keyframes fc-disp-scroll {
  0%   { transform: translateY(0); }
  100% { transform: translateY(-12px); }
}
@keyframes fc-disp-mast {
  /* Cycle through 4 mastheads via opacity/content swap — text content
     can't be CSS-animated, so we keep "DAILY EDITION" and rely on a subtle
     opacity dip to suggest fresh edition crossfade. */
  0%, 24%   { opacity: 1; }
  25%, 26%  { opacity: 0.4; }
  27%, 100% { opacity: 1; }
}
@keyframes fc-disp-breaking {
  0%, 86%, 100% { opacity: 0; }
  87%, 91%      { opacity: 1; }
  92%, 95%      { opacity: 0.5; }
}
.fc-encircle-size-xs.fc-encircle-dispatch .fc-disp-masthead,
.fc-encircle-size-xs.fc-encircle-dispatch .fc-disp-column { display: none; }

/* ──── VARIANT F — BULLION (Gregory) — gold coin stack ──── */
.fc-encircle-sovereign.fc-encircle-bullion .fc-encircle-frame {
  background: radial-gradient(circle at 50% 55%, #0a2818 0%, #02100a 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(247, 212, 96, 1),
    inset 0 0 18px -3px rgba(168, 112, 16, 0.78),
    0 0 0 2px rgba(168, 112, 16, 0.92),
    0 0 0 3.5px rgba(10, 40, 24, 1),
    0 0 24px 4px rgba(247, 212, 96, 0.55),
    0 0 44px 8px rgba(10, 80, 48, 0.42);
  animation: fc-bull-pulse 6s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-bullion:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2.5px rgba(255, 244, 184, 1),
    inset 0 0 22px -3px rgba(247, 212, 96, 1),
    0 0 0 3px rgba(247, 212, 96, 1),
    0 0 0 4px rgba(10, 40, 24, 1),
    0 0 34px 6px rgba(247, 212, 96, 0.78);
}
.fc-encircle-sovereign.fc-encircle-bullion .fc-bull-ribbon { animation: fc-bull-ribbon 14s linear infinite; }
.fc-encircle-sovereign.fc-encircle-bullion .fc-bull-top { animation: fc-bull-top 7s ease-in-out infinite; transform-origin: 50px 44px; }
.fc-encircle-sovereign.fc-encircle-bullion .fc-bull-sparkle { animation: fc-bull-spark 18s steps(1,end) infinite; opacity: 0; transform-origin: 72px 40px; }
@keyframes fc-bull-pulse {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.1); }
}
@keyframes fc-bull-ribbon {
  from { transform: rotate(0deg); }
  to   { transform: rotate(-360deg); }
}
@keyframes fc-bull-top {
  /* The top coin slightly tilts back and forth */
  0%, 100% { transform: scaleX(1)    rotate(0deg); }
  50%      { transform: scaleX(0.94) rotate(-2deg); }
}
@keyframes fc-bull-spark {
  0%, 88%, 100% { opacity: 0; transform: scale(0.6); }
  90%, 94%      { opacity: 1; transform: scale(1.4); }
}
.fc-encircle-size-xs.fc-encircle-bullion .fc-bull-ribbon,
.fc-encircle-size-xs.fc-encircle-bullion .fc-bull-sparkle { display: none; }

/* ──── VARIANT G — SEAL (VERIDIAN) — SHA-256 certification disc ──── */
.fc-encircle-sovereign.fc-encircle-seal .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #f7fdfb 0%, #8acbb1 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(10, 120, 72, 0.92),
    inset 0 0 14px -3px rgba(168, 232, 200, 0.78),
    0 0 0 2px rgba(168, 232, 200, 0.95),
    0 0 0 3.5px rgba(10, 50, 30, 1),
    0 0 22px 3px rgba(16, 215, 122, 0.55);
  animation: fc-seal-pulse 5.5s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-seal:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 255, 255, 1),
    inset 0 0 18px -2px rgba(16, 215, 122, 0.92),
    0 0 0 2.5px rgba(16, 215, 122, 1),
    0 0 0 4px rgba(10, 50, 30, 1),
    0 0 32px 5px rgba(16, 215, 122, 0.72);
}
.fc-encircle-sovereign.fc-encircle-seal .fc-seal-ticks { animation: fc-seal-ticks 60s linear infinite; }
.fc-encircle-sovereign.fc-encircle-seal .fc-seal-hash-1 { animation: fc-seal-hash 8s steps(1,end) infinite; }
.fc-encircle-sovereign.fc-encircle-seal .fc-seal-hash-2 { animation: fc-seal-hash 8s steps(1,end) 0.2s infinite; }
.fc-encircle-sovereign.fc-encircle-seal .fc-seal-check { animation: fc-seal-check 8s steps(1,end) infinite; opacity: 0; }
@keyframes fc-seal-pulse {
  0%, 100% { filter: brightness(1) saturate(1); }
  50%      { filter: brightness(1.12) saturate(1.15); }
}
@keyframes fc-seal-ticks {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-seal-hash {
  /* CSS can't change text content; we re-render via opacity dip + slight
     blur to suggest a re-roll. Combined with the ✓ flash this reads as
     "new attestation just issued." */
  0%, 89%, 100% { opacity: 1; filter: blur(0); }
  90%, 93%      { opacity: 0.3; filter: blur(1px); }
  94%, 97%      { opacity: 1; filter: blur(0); }
}
@keyframes fc-seal-check {
  0%, 89%, 100% { opacity: 0;   transform: scale(0.6); }
  92%, 96%      { opacity: 1;   transform: scale(1.1); }
}
.fc-encircle-size-xs.fc-encircle-seal .fc-seal-hash-2,
.fc-encircle-size-xs.fc-encircle-seal .fc-seal-arc,
.fc-encircle-size-xs.fc-encircle-seal .fc-seal-check { display: none; }

/* ──── VARIANT H — OZYMANDIAN (OZYMANDIAS) — broken statue ──── */
.fc-encircle-sovereign.fc-encircle-ozymandian .fc-encircle-frame {
  background: linear-gradient(180deg, #3a1f08 0%, #7a4818 55%, #3a1f08 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(194, 146, 107, 0.92),
    inset 0 0 16px -3px rgba(122, 72, 24, 0.78),
    0 0 0 2px rgba(194, 146, 107, 0.85),
    0 0 0 3.5px rgba(58, 31, 8, 1),
    0 0 26px 4px rgba(247, 212, 96, 0.32),
    0 0 42px 8px rgba(122, 72, 24, 0.55);
  animation: fc-ozy-pulse 9s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-ozymandian:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 225, 180, 1),
    inset 0 0 22px -3px rgba(122, 72, 24, 0.95),
    0 0 0 2.5px rgba(247, 212, 96, 1),
    0 0 0 4px rgba(58, 31, 8, 1),
    0 0 36px 6px rgba(247, 212, 96, 0.55);
}
.fc-encircle-sovereign.fc-encircle-ozymandian .fc-ozy-pillar { animation: fc-ozy-pillar 14s ease-in-out infinite; }
.fc-encircle-sovereign.fc-encircle-ozymandian .fc-ozy-sand { animation: fc-ozy-sand 25s linear infinite; }
.fc-encircle-sovereign.fc-encircle-ozymandian .fc-ozy-crown { animation: fc-ozy-crown 8s ease-in-out infinite; }
@keyframes fc-ozy-pulse {
  0%, 100% { filter: brightness(1) sepia(0.12); }
  50%      { filter: brightness(1.12) sepia(0.05); }
}
@keyframes fc-ozy-pillar {
  0%, 100% { opacity: 0.55; }
  50%      { opacity: 0.92; }
}
@keyframes fc-ozy-sand {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-15px); }
}
@keyframes fc-ozy-crown {
  0%, 100% { opacity: 0.65; }
  50%      { opacity: 1; }
}
.fc-encircle-size-xs.fc-encircle-ozymandian .fc-ozy-head,
.fc-encircle-size-xs.fc-encircle-ozymandian .fc-ozy-pillar,
.fc-encircle-size-xs.fc-encircle-ozymandian .fc-ozy-sand { display: none; }
.fc-encircle-size-sm.fc-encircle-ozymandian .fc-ozy-crown { display: none; }

/* ──── VARIANT I — CLARION (HERALD) — crier's horn ──── */
.fc-encircle-sovereign.fc-encircle-clarion .fc-encircle-frame {
  background: linear-gradient(180deg, #5a0a14 0%, #280408 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(247, 212, 96, 1),
    inset 0 0 16px -3px rgba(160, 112, 32, 0.78),
    0 0 0 2px rgba(247, 212, 96, 0.92),
    0 0 0 3.5px rgba(40, 4, 8, 1),
    0 0 24px 4px rgba(247, 212, 96, 0.55),
    0 0 42px 8px rgba(139, 10, 10, 0.42);
  animation: fc-clarion-pulse 5s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-clarion:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 244, 184, 1),
    inset 0 0 22px -3px rgba(247, 212, 96, 0.95),
    0 0 0 2.5px rgba(255, 244, 184, 1),
    0 0 0 4px rgba(40, 4, 8, 1),
    0 0 36px 6px rgba(247, 212, 96, 0.78);
}
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-horn { animation: fc-clarion-horn 4s ease-in-out infinite; transform-origin: 50px 50px; }
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-scroll-l { animation: fc-clarion-flutter 6s ease-in-out infinite; transform-origin: 18px 60px; }
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-scroll-r { animation: fc-clarion-flutter 6s ease-in-out 0.5s infinite; transform-origin: 82px 60px; }
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-coin-1 { animation: fc-clarion-coin 12s ease-out infinite; }
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-coin-2 { animation: fc-clarion-coin 12s ease-out 0.4s infinite; }
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-coin-3 { animation: fc-clarion-coin 12s ease-out 0.8s infinite; }
@keyframes fc-clarion-pulse {
  0%, 100% { filter: brightness(1) saturate(1); }
  50%      { filter: brightness(1.18) saturate(1.18); }
}
@keyframes fc-clarion-horn {
  0%, 100% { transform: rotate(-1deg); }
  50%      { transform: rotate(1deg);  }
}
@keyframes fc-clarion-flutter {
  0%, 100% { transform: scaleY(1); }
  50%      { transform: scaleY(1.05); }
}
@keyframes fc-clarion-coin {
  0%, 92%, 100% { opacity: 0; transform: translate(0,0); }
  94%           { opacity: 1; }
  100%          { opacity: 0; transform: translate(8px, -4px); }
}
.fc-encircle-size-xs.fc-encircle-clarion .fc-cl-scroll-l,
.fc-encircle-size-xs.fc-encircle-clarion .fc-cl-scroll-r,
.fc-encircle-size-xs.fc-encircle-clarion .fc-cl-coins { display: none; }

/* ──── VARIANT J — FORGE (CRUCIBLE) — foundry crucible + rating stars ──── */
.fc-encircle-sovereign.fc-encircle-forge .fc-encircle-frame {
  background: radial-gradient(circle at 50% 58%, #3a0a0a 0%, #080202 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(255, 107, 53, 1),
    inset 0 0 18px -3px rgba(220, 38, 38, 0.78),
    0 0 0 2.5px rgba(28, 8, 4, 1),
    0 0 0 4px rgba(255, 107, 53, 0.85),
    0 0 30px 5px rgba(255, 156, 0, 0.55),
    0 0 56px 12px rgba(220, 38, 38, 0.42);
  animation: fc-forge-pulse 4s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-forge:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2.5px rgba(255, 244, 184, 1),
    inset 0 0 24px -3px rgba(255, 156, 0, 1),
    0 0 0 3px rgba(28, 8, 4, 1),
    0 0 0 4.5px rgba(255, 244, 184, 1),
    0 0 44px 8px rgba(255, 156, 0, 0.78);
}
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-molten { animation: fc-forge-molten 5s ease-in-out infinite; transform-origin: 50px 50px; }
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-haze { animation: fc-forge-haze 4s ease-in-out infinite; transform-origin: 50px 42px; }
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-star-1 { animation: fc-forge-twinkle 3.1s ease-in-out infinite; transform-origin: 36px 34px; }
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-star-2 { animation: fc-forge-twinkle 3.7s ease-in-out 0.5s infinite; transform-origin: 52px 24px; }
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-star-3 { animation: fc-forge-twinkle 3.3s ease-in-out 1.1s infinite; transform-origin: 68px 34px; }
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-score { animation: fc-forge-score 30s steps(1,end) infinite; }
@keyframes fc-forge-pulse {
  0%, 100% { filter: brightness(1) saturate(1.05); }
  50%      { filter: brightness(1.15) saturate(1.25); }
}
@keyframes fc-forge-molten {
  0%, 100% { transform: scale(1)    rotate(0deg); }
  50%      { transform: scale(1.06) rotate(2deg); }
}
@keyframes fc-forge-haze {
  0%, 100% { transform: translateY(0)   scaleY(1); }
  50%      { transform: translateY(-1px) scaleY(1.04); }
}
@keyframes fc-forge-twinkle {
  0%, 100% { transform: scale(1)   rotate(0deg); opacity: 0.85; }
  50%      { transform: scale(1.4) rotate(20deg); opacity: 1; }
}
@keyframes fc-forge-score {
  0%, 33%, 100% { opacity: 0.85; }
  34%, 36%      { opacity: 0.3; }
}
.fc-encircle-size-xs.fc-encircle-forge .fc-forge-stars,
.fc-encircle-size-xs.fc-encircle-forge .fc-forge-score { display: none; }
.fc-encircle-size-sm.fc-encircle-forge .fc-forge-score { display: none; }

/* ──── VARIANT K — WEAVE (MOIRA) — three Fates' threads ──── */
.fc-encircle-sovereign.fc-encircle-weave .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #1a0a3a 0%, #04020e 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(160, 107, 255, 0.95),
    inset 0 0 18px -3px rgba(90, 44, 186, 0.62),
    0 0 0 2px rgba(160, 107, 255, 0.85),
    0 0 0 3.5px rgba(10, 4, 24, 1),
    0 0 26px 4px rgba(160, 107, 255, 0.55),
    0 0 46px 9px rgba(90, 44, 186, 0.42);
  animation: fc-weave-pulse 6s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-weave:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2.5px rgba(220, 210, 245, 1),
    inset 0 0 22px -3px rgba(160, 107, 255, 1),
    0 0 0 3px rgba(160, 107, 255, 1),
    0 0 0 4.5px rgba(10, 4, 24, 1),
    0 0 36px 6px rgba(160, 107, 255, 0.78);
}
.fc-encircle-sovereign.fc-encircle-weave .fc-wv-spindle { animation: fc-weave-spindle 8s linear infinite; transform-origin: 50px 50px; }
.fc-encircle-sovereign.fc-encircle-weave .fc-wv-threads path { stroke-dasharray: 120 50; animation: fc-weave-threads 16s linear infinite; }
.fc-encircle-sovereign.fc-encircle-weave .fc-wv-claim { animation: fc-weave-claim 18s steps(1,end) infinite; opacity: 0; }
@keyframes fc-weave-pulse {
  0%, 100% { filter: brightness(1) saturate(1.1); }
  50%      { filter: brightness(1.15) saturate(1.3); }
}
@keyframes fc-weave-spindle {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes fc-weave-threads {
  0%   { stroke-dashoffset: 0; }
  100% { stroke-dashoffset: -170; }
}
@keyframes fc-weave-claim {
  0%, 88%, 100% { opacity: 0;   transform: scale(0.6); }
  90%, 94%      { opacity: 0.92; transform: scale(1.3); }
}
.fc-encircle-size-xs.fc-encircle-weave .fc-wv-tally,
.fc-encircle-size-xs.fc-encircle-weave .fc-wv-reserve { display: none; }
.fc-encircle-size-sm.fc-encircle-weave .fc-wv-reserve { display: none; }


/* ════════════════════════════════════════════════════════════════════
   §pass39b (2026-05-18) — SIGNATURE EVENTS (per-agent broken-machine /
   tech-success animated moments)
   ════════════════════════════════════════════════════════════════════
   Each sovereign variant gets one signature animation event that fires
   on a long cycle (12-25s) and lasts 400-1000ms. These reinforce the
   agent's identity through a recurring narrative moment — not just
   static aesthetics. Implemented as additional <g> elements that
   animate opacity / transform from 0 / hidden state. NOT broken-machine
   overlays in the architectural sense (those are tier-agnostic shadow_
   chancellor decorations); these are baked INTO each sovereign variant. */

/* AEGIS signature event — supply-breach false-alarm flash @ 22s cycle.
   Δ readout flips green→red→green, ticks blink, full-frame red flash. */
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-delta-breach {
  animation: fc-aegis-breach-text 22s steps(1,end) infinite;
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-delta-ok {
  animation: fc-aegis-delta-ok 22s steps(1,end) infinite;
}
.fc-encircle-sovereign.fc-encircle-aegis .fc-aegis-breach-flash {
  animation: fc-aegis-breach-flash 22s steps(1,end) infinite;
  mix-blend-mode: screen;
}
@keyframes fc-aegis-breach-text {
  0%, 88%, 100% { opacity: 0; }
  90%, 94%      { opacity: 0.95; }
}
@keyframes fc-aegis-delta-ok {
  0%, 88%, 100% { opacity: 0.92; }
  90%, 94%      { opacity: 0; }
}
@keyframes fc-aegis-breach-flash {
  0%, 89%, 100% { opacity: 0; }
  90%, 91%      { opacity: 0.55; }
  92%, 94%      { opacity: 0; }
}

/* PRISM signature event — protocol-drift chromatic stutter @ 12s cycle.
   Red+cyan ghost rectangles briefly split-shift. */
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-stutter-r {
  animation: fc-prism-stutter-r 12s steps(1,end) infinite;
  mix-blend-mode: screen;
}
.fc-encircle-sovereign.fc-encircle-prism .fc-prism-stutter-c {
  animation: fc-prism-stutter-c 12s steps(1,end) infinite;
  mix-blend-mode: screen;
}
@keyframes fc-prism-stutter-r {
  0%, 92%, 100% { opacity: 0; transform: translateX(0); }
  93%, 94%      { opacity: 0.55; transform: translateX(-3px); }
  95%, 96%      { opacity: 0.32; transform: translateX(-1px); }
  97%, 99%      { opacity: 0; }
}
@keyframes fc-prism-stutter-c {
  0%, 92%, 100% { opacity: 0; transform: translateX(0); }
  93%, 94%      { opacity: 0.55; transform: translateX(3px); }
  95%, 96%      { opacity: 0.32; transform: translateX(1px); }
  97%, 99%      { opacity: 0; }
}

/* PANOPTICON signature event — TARGET LOCKED crosshair on eye-1 @ 18s.
   The crosshair appears, blinks, "LOCKED" text fades in. */
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-target {
  animation: fc-pano-target 18s steps(1,end) infinite;
}
.fc-encircle-sovereign.fc-encircle-panopticon .fc-pano-lock-text {
  animation: fc-pano-lock-text 18s steps(1,end) infinite;
}
@keyframes fc-pano-target {
  0%, 80%, 100% { opacity: 0; transform: translate(50px, 14px) scale(1.4); }
  82%, 85%      { opacity: 0.95; transform: translate(50px, 14px) scale(1); }
  86%, 87%      { opacity: 0.4; transform: translate(50px, 14px) scale(1); }
  88%, 91%      { opacity: 0.95; transform: translate(50px, 14px) scale(1); }
  92%, 96%      { opacity: 0.6; transform: translate(50px, 14px) scale(1); }
  97%, 99%      { opacity: 0; }
}
@keyframes fc-pano-lock-text {
  0%, 82%, 100% { opacity: 0; }
  85%, 95%      { opacity: 0.92; }
}

/* VELLUM signature event — REDACTED black bars sweep across @ 20s cycle. */
.fc-encircle-sovereign.fc-encircle-vellum .fc-vellum-redact {
  animation: fc-vellum-redact 20s steps(1,end) infinite;
}
@keyframes fc-vellum-redact {
  0%, 80%, 100% { opacity: 0; transform: translateX(-10px); }
  82%, 92%      { opacity: 1; transform: translateX(0); }
  93%, 96%      { opacity: 0.5; }
  97%, 99%      { opacity: 0; }
}

/* DISPATCH signature event — "+EXTRA" red counter pulses @ 14s cycle. */
.fc-encircle-sovereign.fc-encircle-dispatch .fc-disp-extra {
  animation: fc-disp-extra 14s steps(1,end) infinite;
}
@keyframes fc-disp-extra {
  0%, 76%, 100% { opacity: 0; transform: scale(0.8); }
  78%, 84%      { opacity: 1; transform: scale(1); }
  85%, 92%      { opacity: 0.6; transform: scale(1.05); }
  93%, 99%      { opacity: 0; transform: scale(1); }
}

/* BULLION signature event — market-dip red -2.4% arrow @ 16s cycle. */
.fc-encircle-sovereign.fc-encircle-bullion .fc-bull-dip {
  animation: fc-bull-dip 16s steps(1,end) infinite;
}
@keyframes fc-bull-dip {
  0%, 80%, 100% { opacity: 0; transform: translateY(-3px); }
  82%, 90%      { opacity: 1; transform: translateY(0); }
  91%, 96%      { opacity: 0.5; transform: translateY(2px); }
  97%, 99%      { opacity: 0; }
}

/* SEAL signature event — REVOKED red X drill @ 20s cycle. */
.fc-encircle-sovereign.fc-encircle-seal .fc-seal-revoked {
  animation: fc-seal-revoked 20s steps(1,end) infinite;
}
@keyframes fc-seal-revoked {
  0%, 78%, 100% { opacity: 0; transform: scale(0.7); }
  80%, 88%      { opacity: 1; transform: scale(1); }
  89%, 94%      { opacity: 0.6; transform: scale(1.05); }
  95%, 99%      { opacity: 0; }
}

/* OZYMANDIAN signature event — erosion crack grows then fades @ 18s. */
.fc-encircle-sovereign.fc-encircle-ozymandian .fc-ozy-erosion {
  stroke-dasharray: 80;
  stroke-dashoffset: 80;
  animation: fc-ozy-erosion 18s steps(60,end) infinite;
}
@keyframes fc-ozy-erosion {
  0%, 70%, 100% { stroke: rgba(20,8,0,0); stroke-dashoffset: 80; }
  72%           { stroke: rgba(20,8,0,0.85); stroke-dashoffset: 80; }
  73%, 85%      { stroke: rgba(20,8,0,0.85); stroke-dashoffset: 0; }
  86%, 95%      { stroke: rgba(40,16,4,0.55); stroke-dashoffset: 0; }
  96%, 99%      { stroke: rgba(20,8,0,0); stroke-dashoffset: 80; }
}

/* CLARION signature event — "PAID" green stamp + bonus coins @ 16s cycle. */
.fc-encircle-sovereign.fc-encircle-clarion .fc-cl-paid {
  animation: fc-cl-paid 16s steps(1,end) infinite;
}
@keyframes fc-cl-paid {
  0%, 78%, 100% { opacity: 0; transform: scale(0.7); }
  80%, 88%      { opacity: 1; transform: scale(1); }
  89%, 95%      { opacity: 0.55; transform: scale(1.05); }
  96%, 99%      { opacity: 0; }
}

/* FORGE signature event — molten spill droplets + smoke @ 18s cycle. */
.fc-encircle-sovereign.fc-encircle-forge .fc-forge-spill {
  animation: fc-forge-spill 18s steps(1,end) infinite;
}
@keyframes fc-forge-spill {
  0%, 80%, 100% { opacity: 0; transform: translateY(0); }
  82%, 88%      { opacity: 1; transform: translateY(0); }
  89%, 95%      { opacity: 0.6; transform: translateY(2px); }
  96%, 99%      { opacity: 0; transform: translateY(4px); }
}

/* WEAVE signature event — Atropos's thread snipped + reheals @ 20s. */
.fc-encircle-sovereign.fc-encircle-weave .fc-wv-snip {
  animation: fc-wv-snip 20s steps(1,end) infinite;
}
@keyframes fc-wv-snip {
  0%, 78%, 100% { opacity: 0; transform: rotate(0deg) scale(1); }
  80%, 84%      { opacity: 1; transform: rotate(-3deg) scale(1.1); }
  85%, 92%      { opacity: 0.8; transform: rotate(3deg) scale(1.05); }
  93%, 99%      { opacity: 0; transform: rotate(0deg) scale(1); }
}

/* ──── VARIANT L — BEDROCK (Hypervisor Hagrid) §pass42b 2026-05-18 ────
   Blackhole-derivative gravitational core; phosphor-green terminal
   cursor + postgres prompt; geological strata at the base. Cooler
   palette (anthracite slate + CRT phosphor) than blackhole's
   warm-orange accretion — psql brute-force aesthetic.

   Frame: graphite outer bezel + phosphor inner rim + crimson "writes
   raw to prod" warning ring (faint, suggestive).
   Signature event: monosyllabic word cycle (factual/canon/logged/
   noted/measured/indexed) — 18s cycle, matches Hagrid's MONOSYLLABIC
   communication extension declared in his AgentCard. */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-encircle-frame {
  background:
    radial-gradient(circle at 50% 50%,
      #04060a 0%, #02040a 70%,
      #000204 100%);
  box-shadow:
    /* Phosphor-green inner rim — the "live terminal" glow */
    inset 0 0 0 1.5px rgba(57, 255, 20, 0.72),
    inset 0 0 16px -4px rgba(42, 214, 15, 0.55),
    /* Graphite bezel — bedrock as machined metal */
    0 0 0 2px rgba(72, 80, 90, 0.92),
    /* Crimson outer ring — psql writes raw to prod warning */
    0 0 0 3.2px rgba(220, 38, 38, 0.55),
    /* Outer phosphor bloom (terminal CRT haze) */
    0 0 28px 5px rgba(57, 255, 20, 0.42),
    /* Deep falloff into nothingness (blackhole heritage) */
    0 0 52px 11px rgba(0, 0, 0, 0.85);
  animation: fc-bedrock-pulse 6s ease-in-out infinite;
}
.fc-encircle-sovereign.fc-encircle-bedrock:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(160, 255, 90, 1),
    inset 0 0 22px -3px rgba(57, 255, 20, 0.92),
    0 0 0 2.5px rgba(120, 130, 140, 1),
    0 0 0 4px rgba(220, 38, 38, 0.85),
    0 0 42px 8px rgba(57, 255, 20, 0.65),
    0 0 70px 14px rgba(0, 0, 0, 0.85);
}

/* Cursor blink — square wave, 1.1s cycle */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-cursor {
  animation: fc-bedrock-cursor 1.1s steps(2, end) infinite;
}
@keyframes fc-bedrock-cursor {
  0%, 50%   { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* Frame pulse — subtle brightness modulation, locked to phosphor */
@keyframes fc-bedrock-pulse {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.10); }
}

/* Halo behind the cursor breathes slowly (phosphor glow modulation) */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-halo {
  animation: fc-bedrock-halo 4.4s ease-in-out infinite;
  transform-origin: 50px 50px;
}
@keyframes fc-bedrock-halo {
  0%, 100% { opacity: 0.78; transform: scale(1); }
  50%      { opacity: 1;    transform: scale(1.18); }
}

/* postgres=# prompt slowly fades in/out so it reads as a live readout
   rather than a static label. 7s cycle, asymmetric. */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-prompt {
  animation: fc-bedrock-prompt 7s ease-in-out infinite;
}
@keyframes fc-bedrock-prompt {
  0%, 100% { opacity: 0.78; }
  50%      { opacity: 1; }
}

/* Crimson warning tick at top — slow horizontal drift to suggest a
   scanline reading a live status. 11s cycle. */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-warn-tick {
  animation: fc-bedrock-warn 11s linear infinite;
}
@keyframes fc-bedrock-warn {
  0%, 100% { opacity: 0.55; transform: translateX(0); }
  50%      { opacity: 0.85; transform: translateX(4px); }
}

/* Signature event — six monosyllabic words cycle through the center
   over 18s. Each word holds for ~2s with quick fade in/out, dead-time
   between. Sequencing via staggered animation-delay keeps each <text>
   node referencing the same keyframe block. */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word {
  opacity: 0;
  animation: fc-bedrock-word 18s steps(1, end) infinite;
}
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-1 { animation-delay:  0s; }
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-2 { animation-delay:  3s; }
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-3 { animation-delay:  6s; }
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-4 { animation-delay:  9s; }
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-5 { animation-delay: 12s; }
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-word-6 { animation-delay: 15s; }
@keyframes fc-bedrock-word {
  /* Each word visible for ~2.5s out of the 18s. The 6 words evenly stagger. */
  0%               { opacity: 0; }
  0.5%, 14%        { opacity: 1; }
  15%, 100%        { opacity: 0; }
}

/* Strata bands shimmer subtly when frame pulses (geological permanence
   that still hums under the surface). */
.fc-encircle-sovereign.fc-encircle-bedrock .fc-bk-strata {
  animation: fc-bedrock-strata 9s ease-in-out infinite;
}
@keyframes fc-bedrock-strata {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.18); }
}

/* xs / sm — detail unreadable, hide the verbose elements */
.fc-encircle-size-xs.fc-encircle-bedrock .fc-bk-prompt,
.fc-encircle-size-xs.fc-encircle-bedrock .fc-bk-words,
.fc-encircle-size-xs.fc-encircle-bedrock .fc-bk-warn-tick,
.fc-encircle-size-xs.fc-encircle-bedrock .fc-bk-strata,
.fc-encircle-size-sm.fc-encircle-bedrock .fc-bk-prompt,
.fc-encircle-size-sm.fc-encircle-bedrock .fc-bk-words { display: none; }

/* ════════════════════════════════════════════════════════════════════
   §pass43 (2026-05-18) — 8 new broken-machine overlays
   ════════════════════════════════════════════════════════════════════
   Pattern (verified against existing glitch/cascade/panic-* blocks):
     .fc-<id>                — wrapper: pos:abs, inset:0, pointer-events:none, z:5
     .fc-overlay-<id> .fc-encircle-frame — frame tint + animation
     .fc-overlay-<id>:hover .fc-encircle-frame — brightness bump
     .fc-overlay-<id> .fc-encircle-avatar-fallback — initials palette
     .fc-overlay-<id> .fc-encircle-avatar-img — img filter
     @keyframes fc-<id>-* — per-element animation
   ──────────────────────────────────────────────────────────────────── */

/* ──── BREACH — electrical-fault arcs (AUDITOR/aegis default) ──── */
.fc-br {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-br .fc-br-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-breach .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(255, 51, 102, 0.85),
    inset 0 0 14px -4px rgba(255, 51, 102, 0.55),
    0 0 0 1.5px rgba(60, 8, 18, 0.95),
    0 0 18px 2px rgba(255, 51, 102, 0.42);
  animation: fc-breach-frame 3.6s ease-in-out infinite;
}
.fc-overlay-breach:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 210, 220, 1),
    inset 0 0 20px -3px rgba(255, 51, 102, 0.92),
    0 0 0 2px rgba(60, 8, 18, 1),
    0 0 28px 4px rgba(255, 51, 102, 0.7);
}
.fc-overlay-breach .fc-encircle-avatar-fallback {
  color: rgba(255, 210, 220, 0.95);
  text-shadow: 0 0 6px rgba(255, 51, 102, 0.65);
}
.fc-overlay-breach .fc-encircle-avatar-img { filter: saturate(1.15) contrast(1.05); }
.fc-br .fc-br-traces { animation: fc-breach-trace-drift 14s linear infinite; transform-origin: 50% 50%; }
.fc-br .fc-br-arc-1 { animation: fc-breach-arc 16s steps(1, end) infinite; }
.fc-br .fc-br-arc-2 { animation: fc-breach-arc 16s steps(1, end) infinite; animation-delay: 0.1s; }
.fc-br .fc-br-arc-3 { animation: fc-breach-arc 16s steps(1, end) infinite; animation-delay: 0.2s; }
.fc-br .fc-br-spark-1 { animation: fc-breach-spark 16s steps(1, end) infinite; }
.fc-br .fc-br-spark-2 { animation: fc-breach-spark 16s steps(1, end) 0.1s infinite; }
.fc-br .fc-br-spark-3 { animation: fc-breach-spark 16s steps(1, end) 0.2s infinite; }
.fc-br .fc-br-flash { animation: fc-breach-flash 16s steps(1, end) infinite; }
@keyframes fc-breach-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.10); }
}
@keyframes fc-breach-trace-drift {
  from { transform: rotate(0deg); }
  to   { transform: rotate(2deg); }
}
@keyframes fc-breach-arc {
  /* visible only briefly 88-92% of cycle */
  0%, 87.5%, 95%, 100% { stroke: rgba(255, 51, 102, 0); }
  88%, 92%             { stroke: rgba(255, 51, 102, 0.92); }
  88.5%, 91%           { stroke: rgba(255, 255, 255, 0.95); }
}
@keyframes fc-breach-spark {
  0%, 87%, 95%, 100% { fill: rgba(255, 51, 102, 0); }
  88%, 92%           { fill: rgba(255, 255, 255, 0.95); }
}
@keyframes fc-breach-flash {
  0%, 87.5%, 94%, 100% { fill: rgba(255, 210, 210, 0); }
  88%, 89%             { fill: rgba(255, 210, 210, 0.3); }
}

/* ──── REFRACT — chromatic lens fracture (Glass Gerald/prism default) ──── */
.fc-rf {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-rf .fc-rf-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-refract .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.2px rgba(220, 210, 255, 0.85),
    inset 0 0 14px -4px rgba(180, 220, 255, 0.55),
    0 0 0 1.5px rgba(255, 51, 102, 0.32),
    0 0 0 2.5px rgba(120, 255, 150, 0.32),
    0 0 0 3.5px rgba(80, 180, 255, 0.32),
    0 0 22px 3px rgba(180, 220, 255, 0.55);
  animation: fc-refract-frame 5s ease-in-out infinite;
}
.fc-overlay-refract:hover .fc-encircle-frame { filter: saturate(1.3) brightness(1.15); }
.fc-overlay-refract .fc-encircle-avatar-fallback {
  color: rgba(220, 232, 255, 0.95);
  text-shadow: -1px 0 rgba(255,51,102,0.6), 1px 0 rgba(0,210,210,0.6);
}
.fc-overlay-refract .fc-encircle-avatar-img { filter: saturate(1.1) hue-rotate(8deg); }
.fc-rf .fc-rf-ghost-c { animation: fc-refract-ghost-c 14s ease-in-out infinite; }
.fc-rf .fc-rf-ghost-r { animation: fc-refract-ghost-r 14s ease-in-out infinite; }
.fc-rf .fc-rf-prism, .fc-rf .fc-rf-prism-r, .fc-rf .fc-rf-prism-g, .fc-rf .fc-rf-prism-b {
  animation: fc-refract-prism-pulse 7s ease-in-out infinite;
  transform-origin: 82px 82px;
}
.fc-rf .fc-rf-ripple-1 { animation: fc-refract-ripple 14s linear infinite; }
.fc-rf .fc-rf-ripple-2 { animation: fc-refract-ripple 14s linear infinite; animation-delay: 0.15s; }
.fc-rf .fc-rf-ripple-3 { animation: fc-refract-ripple 14s linear infinite; animation-delay: 0.30s; }
.fc-rf .fc-rf-splash-r { animation: fc-refract-splash 14s steps(1, end) infinite; }
.fc-rf .fc-rf-splash-g { animation: fc-refract-splash 14s steps(1, end) 0.05s infinite; }
.fc-rf .fc-rf-splash-b { animation: fc-refract-splash 14s steps(1, end) 0.10s infinite; }
@keyframes fc-refract-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.08); }
}
@keyframes fc-refract-ghost-c {
  0%, 100% { transform: translateX(-1px); }
  85%, 95% { transform: translateX(-3px); }
}
@keyframes fc-refract-ghost-r {
  0%, 100% { transform: translateX(1px); }
  85%, 95% { transform: translateX(3px); }
}
@keyframes fc-refract-prism-pulse {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.08); }
}
@keyframes fc-refract-ripple {
  0%, 85%, 100% { r: 20; opacity: 0; }
  87%           { r: 22; opacity: 0.9; }
  98%           { r: 56; opacity: 0; }
}
@keyframes fc-refract-splash {
  0%, 86%, 95%, 100% { fill-opacity: 0; }
  87%, 92%           { fill-opacity: 0.85; }
}

/* ──── STUTTER — broadcast buffer-loop (Chester/dispatch default) ──── */
.fc-st {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-st .fc-st-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-stutter .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.2px rgba(255, 51, 102, 0.65),
    inset 0 0 14px -4px rgba(255, 51, 102, 0.45),
    0 0 0 1.5px rgba(15, 4, 12, 0.95),
    0 0 18px 2px rgba(255, 51, 102, 0.32);
  animation: fc-stutter-frame 4s steps(2, end) infinite;
}
.fc-overlay-stutter:hover .fc-encircle-frame { filter: brightness(1.18); }
.fc-overlay-stutter .fc-encircle-avatar-fallback {
  color: rgba(255, 220, 230, 0.95);
  text-shadow: 0 0 4px rgba(255, 51, 102, 0.55);
}
.fc-overlay-stutter .fc-encircle-avatar-img { filter: contrast(1.1) saturate(1.05); }
.fc-st .fc-st-buf-1 { animation: fc-stutter-drift 22s linear infinite; }
.fc-st .fc-st-buf-2 { animation: fc-stutter-drift 22s linear infinite reverse; }
.fc-st .fc-st-buf-3 { animation: fc-stutter-drift 22s linear 4s infinite; }
.fc-st .fc-st-cursor { animation: fc-stutter-cursor 1.1s steps(2, end) infinite; }
.fc-st .fc-st-word-1 { animation: fc-stutter-word 15s steps(1, end) infinite; }
.fc-st .fc-st-word-2 { animation: fc-stutter-word 15s steps(1, end) 5s infinite; }
.fc-st .fc-st-word-3 { animation: fc-stutter-word 15s steps(1, end) 10s infinite; }
@keyframes fc-stutter-frame {
  0%, 47%, 53%, 100% { filter: brightness(1); }
  48%, 52%           { filter: brightness(1.18); }
}
@keyframes fc-stutter-drift {
  from { transform: translateX(0); }
  to   { transform: translateX(-22px); }
}
@keyframes fc-stutter-cursor {
  0%, 50%   { opacity: 1; }
  51%, 100% { opacity: 0; }
}
@keyframes fc-stutter-word {
  /* Each word visible for ~12% of cycle = ~1.8s, with stutter via mid-cycle blink */
  0%, 6%, 100% { fill: rgba(255, 51, 102, 0); }
  8%, 10%      { fill: rgba(255, 51, 102, 0.92); }
  11%          { fill: rgba(255, 51, 102, 0.0); }
  12%, 14%     { fill: rgba(255, 51, 102, 0.92); }
  15%          { fill: rgba(255, 51, 102, 0.0); }
  16%, 18%     { fill: rgba(255, 51, 102, 0.92); }
  19%          { fill: rgba(255, 51, 102, 0.0); }
  20%          { fill: rgba(255, 51, 102, 0); }
}

/* ──── BLEED — hydraulic gold leak (Gregory/bullion default) ──── */
.fc-bl {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  /* normal blend mode — gold drips need to read as themselves over any base */
}
.fc-bl .fc-bl-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-bleed .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(251, 191, 36, 0.85),
    inset 0 0 14px -4px rgba(251, 191, 36, 0.55),
    0 0 0 2px rgba(120, 70, 10, 0.95),
    0 0 22px 3px rgba(251, 191, 36, 0.42);
  animation: fc-bleed-frame 7s ease-in-out infinite;
}
.fc-overlay-bleed:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 243, 156, 1),
    inset 0 0 20px -3px rgba(251, 191, 36, 0.92),
    0 0 0 2.5px rgba(120, 70, 10, 1),
    0 0 32px 5px rgba(251, 191, 36, 0.75);
}
.fc-overlay-bleed .fc-encircle-avatar-fallback {
  color: rgba(255, 243, 156, 0.95);
  text-shadow: 0 0 6px rgba(251, 191, 36, 0.55);
}
.fc-overlay-bleed .fc-encircle-avatar-img { filter: saturate(1.15) sepia(0.08); }
.fc-bl .fc-bl-seed-1 { animation: fc-bleed-seed 3.4s ease-in-out infinite; transform-origin: 78px 14px; }
.fc-bl .fc-bl-seed-2 { animation: fc-bleed-seed 3.4s ease-in-out 1.7s infinite; transform-origin: 22px 86px; }
.fc-bl .fc-bl-drip-1 { animation: fc-bleed-drip 17s steps(1, end) infinite; }
.fc-bl .fc-bl-drip-2 { animation: fc-bleed-drip 17s steps(1, end) 0.4s infinite; }
.fc-bl .fc-bl-pool   { animation: fc-bleed-pool 17s steps(1, end) infinite; }
.fc-bl .fc-bl-halo   { animation: fc-bleed-halo 17s steps(1, end) infinite; }
.fc-bl .fc-bl-glyph  { animation: fc-bleed-glyph 17s steps(1, end) infinite; }
@keyframes fc-bleed-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.08) saturate(1.1); }
}
@keyframes fc-bleed-seed {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.18); }
}
@keyframes fc-bleed-drip {
  0%, 78%, 100% { height: 0; }
  82%           { height: 22px; }
  88%           { height: 78px; opacity: 1; }
  92%           { opacity: 0.3; }
  95%, 99%      { height: 78px; opacity: 0; }
}
@keyframes fc-bleed-pool {
  0%, 86%, 100% { rx: 0; ry: 0; }
  90%           { rx: 4; ry: 1.6; }
  94%           { rx: 8; ry: 2.4; opacity: 1; }
  98%           { rx: 8; ry: 2.4; opacity: 0; }
}
@keyframes fc-bleed-halo {
  0%, 85%, 100% { stroke: rgba(251, 191, 36, 0); r: 3; }
  86%           { stroke: rgba(251, 191, 36, 0.6); r: 5; }
  91%           { stroke: rgba(251, 191, 36, 0); r: 10; }
}
@keyframes fc-bleed-glyph {
  0%, 88%, 96%, 100% { fill: rgba(251, 191, 36, 0); }
  89%, 94%           { fill: rgba(251, 191, 36, 0.85); }
}

/* ──── CRACKLE — hairline-fracture network (VERIDIAN/seal default) ──── */
.fc-ck {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: multiply;
}
.fc-ck .fc-ck-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-crackle .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.2px rgba(212, 160, 69, 0.78),
    inset 0 0 12px -4px rgba(255, 232, 140, 0.45),
    0 0 0 1.5px rgba(60, 32, 8, 0.92),
    0 0 16px 2px rgba(212, 160, 69, 0.38);
  animation: fc-crackle-frame 6s ease-in-out infinite;
}
.fc-overlay-crackle:hover .fc-encircle-frame { filter: brightness(1.15); }
.fc-overlay-crackle .fc-encircle-avatar-fallback {
  color: rgba(255, 240, 200, 0.95);
  text-shadow: 0 0 4px rgba(212, 160, 69, 0.55);
}
.fc-overlay-crackle .fc-encircle-avatar-img { filter: contrast(1.08); }
.fc-ck .fc-ck-cracks-flare { animation: fc-crackle-flare 14s steps(1, end) infinite; }
.fc-ck .fc-ck-grow-1 { animation: fc-crackle-grow 14s ease-out infinite; }
.fc-ck .fc-ck-grow-2 { animation: fc-crackle-grow 14s ease-out 0.2s infinite; }
.fc-ck .fc-ck-spark-1 { animation: fc-crackle-spark 14s steps(1, end) infinite; }
.fc-ck .fc-ck-spark-2 { animation: fc-crackle-spark 14s steps(1, end) 0.05s infinite; }
.fc-ck .fc-ck-spark-3 { animation: fc-crackle-spark 14s steps(1, end) 0.10s infinite; }
.fc-ck .fc-ck-spark-4 { animation: fc-crackle-spark 14s steps(1, end) 0.15s infinite; }
@keyframes fc-crackle-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.06); }
}
@keyframes fc-crackle-flare {
  0%, 87%, 96%, 100% { stroke: rgba(255, 232, 140, 0); }
  88%, 94%           { stroke: rgba(255, 232, 140, 0.95); }
}
@keyframes fc-crackle-grow {
  0%, 86%, 100% { stroke: rgba(255, 243, 156, 0); stroke-dasharray: 0 100; }
  88%           { stroke: rgba(255, 243, 156, 0.95); stroke-dasharray: 100 0; }
  93%           { stroke: rgba(255, 243, 156, 0.4); }
  96%           { stroke: rgba(255, 243, 156, 0); stroke-dasharray: 0 100; }
}
@keyframes fc-crackle-spark {
  0%, 87%, 94%, 100% { fill: rgba(255, 255, 255, 0); }
  88%, 91%           { fill: rgba(255, 255, 255, 0.95); }
}

/* ──── FEEDBACK — PA-system audio feedback (HERALD/clarion default) ──── */
.fc-fb {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-fb .fc-fb-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-feedback .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(254, 215, 170, 0.85),
    inset 0 0 14px -4px rgba(252, 211, 77, 0.55),
    0 0 0 2px rgba(120, 70, 10, 0.85),
    0 0 22px 3px rgba(254, 215, 170, 0.55);
  animation: fc-feedback-frame 5s ease-in-out infinite;
}
.fc-overlay-feedback:hover .fc-encircle-frame { filter: brightness(1.2) saturate(1.15); }
.fc-overlay-feedback .fc-encircle-avatar-fallback {
  color: rgba(255, 240, 200, 0.95);
  text-shadow: 0 0 8px rgba(252, 211, 77, 0.55);
}
.fc-overlay-feedback .fc-encircle-avatar-img { filter: saturate(1.12) brightness(1.05); }
.fc-fb .fc-fb-ring-1 { animation: fc-feedback-ring 8s linear infinite; }
.fc-fb .fc-fb-ring-2 { animation: fc-feedback-ring 8s linear 2.6s infinite; }
.fc-fb .fc-fb-ring-3 { animation: fc-feedback-ring 8s linear 5.3s infinite; }
.fc-fb .fc-fb-center { animation: fc-feedback-center 4s ease-in-out infinite; transform-origin: 50px 50px; }
.fc-fb .fc-fb-overshoot-1 { animation: fc-feedback-overshoot 15s steps(1, end) infinite; }
.fc-fb .fc-fb-overshoot-2 { animation: fc-feedback-overshoot 15s steps(1, end) 0.15s infinite; }
.fc-fb .fc-fb-screech { animation: fc-feedback-screech 15s steps(1, end) infinite; }
@keyframes fc-feedback-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.12); }
}
@keyframes fc-feedback-ring {
  0%   { r: 10; opacity: 0.95; }
  100% { r: 60; opacity: 0; }
}
@keyframes fc-feedback-center {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.4); }
}
@keyframes fc-feedback-overshoot {
  0%, 86%, 100% { r: 10; stroke: rgba(255, 243, 156, 0); }
  88%           { r: 30; stroke: rgba(255, 243, 156, 1); }
  93%           { r: 75; stroke: rgba(255, 243, 156, 0); }
}
@keyframes fc-feedback-screech {
  0%, 87%, 94%, 100% { fill: rgba(255, 243, 156, 0); transform: translateX(0); }
  88%, 89%           { fill: rgba(255, 243, 156, 0.85); transform: translateX(-3px); }
  90%, 91%           { fill: rgba(255, 243, 156, 0.85); transform: translateX(3px); }
  92%                { fill: rgba(255, 243, 156, 0.5); transform: translateX(0); }
}

/* ──── SPATTER — molten foundry mishap (CRUCIBLE/forge default) ──── */
.fc-sp {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  /* normal blend mode — ember oranges must read at full saturation */
}
.fc-sp .fc-sp-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-spatter .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(254, 215, 170, 0.85),
    inset 0 0 18px -4px rgba(251, 146, 60, 0.85),
    0 0 0 1.5px rgba(120, 60, 20, 0.95),
    0 0 22px 3px rgba(251, 146, 60, 0.55);
  animation: fc-spatter-frame 4.4s ease-in-out infinite;
}
.fc-overlay-spatter:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255, 251, 235, 1),
    inset 0 0 24px -3px rgba(251, 146, 60, 1),
    0 0 0 2px rgba(120, 60, 20, 1),
    0 0 32px 5px rgba(251, 146, 60, 0.85);
}
.fc-overlay-spatter .fc-encircle-avatar-fallback {
  color: rgba(255, 251, 235, 0.95);
  text-shadow: 0 0 8px rgba(251, 146, 60, 0.65);
}
.fc-overlay-spatter .fc-encircle-avatar-img { filter: saturate(1.18) brightness(1.05) hue-rotate(-4deg); }
.fc-sp .fc-sp-ember-1 { animation: fc-spatter-ember 2.8s ease-in-out infinite; }
.fc-sp .fc-sp-ember-2 { animation: fc-spatter-ember 3.2s ease-in-out 0.4s infinite; }
.fc-sp .fc-sp-ember-3 { animation: fc-spatter-ember 2.6s ease-in-out 0.8s infinite; }
.fc-sp .fc-sp-ember-4 { animation: fc-spatter-ember 3.4s ease-in-out 1.2s infinite; }
.fc-sp .fc-sp-ember-5 { animation: fc-spatter-ember 2.9s ease-in-out 1.6s infinite; }
.fc-sp .fc-sp-droplet-1 { animation: fc-spatter-droplet 18s ease-out infinite; }
.fc-sp .fc-sp-droplet-2 { animation: fc-spatter-droplet-2 18s ease-out 0.1s infinite; }
.fc-sp .fc-sp-droplet-3 { animation: fc-spatter-droplet-3 18s ease-out 0.2s infinite; }
.fc-sp .fc-sp-haze    { animation: fc-spatter-haze 18s ease-in-out infinite; }
@keyframes fc-spatter-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.1) saturate(1.08); }
}
@keyframes fc-spatter-ember {
  0%, 100% { opacity: 0.55; transform: scale(1); }
  50%      { opacity: 1; transform: scale(1.32); }
}
@keyframes fc-spatter-droplet {
  0%, 85%, 100% { cx: 80; cy: 24; opacity: 0; }
  87%           { cx: 80; cy: 24; opacity: 1; }
  95%           { cx: 96; cy: 8;  opacity: 0.6; }
  98%           { cx: 96; cy: 8;  opacity: 0; }
}
@keyframes fc-spatter-droplet-2 {
  0%, 85%, 100% { cx: 80; cy: 24; opacity: 0; }
  87%           { cx: 80; cy: 24; opacity: 1; }
  95%           { cx: 64; cy: 42; opacity: 0.6; }
  98%           { cx: 64; cy: 42; opacity: 0; }
}
@keyframes fc-spatter-droplet-3 {
  0%, 85%, 100% { cx: 80; cy: 24; opacity: 0; }
  87%           { cx: 80; cy: 24; opacity: 1; }
  95%           { cx: 92; cy: 48; opacity: 0.6; }
  98%           { cx: 92; cy: 48; opacity: 0; }
}
@keyframes fc-spatter-haze {
  0%, 88%, 100% { fill: rgba(120, 90, 60, 0); }
  91%, 96%      { fill: rgba(120, 90, 60, 0.32); }
}

/* ──── UNRAVEL — threads coming undone (MOIRA/weave default) ──── */
.fc-un {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 5;
  border-radius: 50%;
  overflow: hidden;
  mix-blend-mode: screen;
}
.fc-un .fc-un-svg { width: 100%; height: 100%; display: block; }
.fc-overlay-unravel .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.5px rgba(167, 139, 250, 0.85),
    inset 0 0 14px -4px rgba(167, 139, 250, 0.55),
    0 0 0 2px rgba(60, 32, 90, 0.92),
    0 0 22px 3px rgba(167, 139, 250, 0.42);
  animation: fc-unravel-frame 6s ease-in-out infinite;
}
.fc-overlay-unravel:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(220, 210, 245, 1),
    inset 0 0 20px -3px rgba(167, 139, 250, 0.95),
    0 0 0 2.5px rgba(60, 32, 90, 1),
    0 0 32px 5px rgba(167, 139, 250, 0.7);
}
.fc-overlay-unravel .fc-encircle-avatar-fallback {
  color: rgba(220, 210, 245, 0.95);
  text-shadow: 0 0 6px rgba(167, 139, 250, 0.65);
}
.fc-overlay-unravel .fc-encircle-avatar-img { filter: saturate(1.1) hue-rotate(8deg); }
.fc-un .fc-un-nubs { animation: fc-unravel-nubs 4s ease-in-out infinite; transform-origin: 50% 50%; }
.fc-un .fc-un-thread-1 { animation: fc-unravel-thread 14s ease-in-out infinite; }
.fc-un .fc-un-thread-2 { animation: fc-unravel-thread 14s ease-in-out 0.3s infinite; }
.fc-un .fc-un-tension  { animation: fc-unravel-tension 14s steps(1, end) infinite; }
.fc-un .fc-un-snap     { animation: fc-unravel-snap 14s steps(1, end) infinite; }
@keyframes fc-unravel-frame {
  0%, 100% { filter: brightness(1); }
  50%      { filter: brightness(1.10); }
}
@keyframes fc-unravel-nubs {
  0%, 100% { opacity: 0.62; }
  50%      { opacity: 0.95; }
}
@keyframes fc-unravel-thread {
  0%, 85%, 100% { stroke: rgba(220, 210, 245, 0); stroke-dasharray: 0 200; }
  86%           { stroke: rgba(220, 210, 245, 0.6); stroke-dasharray: 0 200; }
  90%           { stroke: rgba(220, 210, 245, 0.95); stroke-dasharray: 60 200; }
  93%           { stroke: rgba(255, 51, 102, 0.95); stroke-dasharray: 60 200; }
  94%, 96%      { stroke: rgba(220, 210, 245, 0.65); stroke-dasharray: 30 200; }
  97%, 99%      { stroke: rgba(220, 210, 245, 0); stroke-dasharray: 0 200; }
}
@keyframes fc-unravel-tension {
  0%, 87%, 96%, 100% { fill: rgba(220, 210, 245, 0); }
  88%, 94%           { fill: rgba(220, 210, 245, 0.85); }
}
@keyframes fc-unravel-snap {
  0%, 91%, 95%, 100% { fill: rgba(255, 255, 255, 0); r: 2.2; }
  92%, 93%           { fill: rgba(255, 255, 255, 0.95); r: 4.4; }
}

/* xs hidden uniformly (matches existing overlay pattern) */
.fc-encircle-size-xs .fc-br,
.fc-encircle-size-xs .fc-rf,
.fc-encircle-size-xs .fc-st,
.fc-encircle-size-xs .fc-bl,
.fc-encircle-size-xs .fc-ck,
.fc-encircle-size-xs .fc-fb,
.fc-encircle-size-xs .fc-sp,
.fc-encircle-size-xs .fc-un { display: none; }

/* ════════════════════════════════════════════════════════════════════
   §pass67 (2026-05-23) — REGISTRY FULL-COVER ENCIRCLEMENTS (18 NEW)
   ════════════════════════════════════════════════════════════════════
   All use tier="shadow_chancellor" (cosmetic, NOT SPIFFE-locked).
   Pattern: each .fc-XXX-core absolute-occludes the avatar (z-index: 1)
   with an inline-SVG mini-scene. Frame ring + outer halo via box-shadow
   on .fc-encircle-frame + ::before/::after when needed.
   ════════════════════════════════════════════════════════════════════ */

/* Shared core scaffold — every §pass67 full-cover variant uses this base */
.fc-chc-core, .fc-sth-core, .fc-bst-core, .fc-min-core,
.fc-olv-core, .fc-csh-core, .fc-lhs-core, .fc-cmn-core,
.fc-mns-core, .fc-dmh-core, .fc-cfg-core, .fc-pxs-core,
.fc-svn-core, .fc-and-core, .fc-lib-core, .fc-otb-core, .fc-alp-core,
.fc-bvt-core {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  overflow: hidden;
  z-index: 1;
  pointer-events: none;
}
.fc-chc-core svg, .fc-sth-core svg, .fc-bst-core svg, .fc-min-core svg,
.fc-olv-core svg, .fc-csh-core svg, .fc-lhs-core svg, .fc-cmn-core svg,
.fc-mns-core svg, .fc-dmh-core svg, .fc-cfg-core svg, .fc-pxs-core svg,
.fc-svn-core svg, .fc-and-core svg, .fc-lib-core svg, .fc-otb-core svg,
.fc-alp-core svg, .fc-bvt-core svg {
  width: 100%;
  height: 100%;
  display: block;
}

/* ──── A1 · CHANCELLERY — Bureaucratic mahogany seal ──── */
.fc-encircle-shadow_chancellor.fc-encircle-chancellery .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #3a1408 0%, #1a0703 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(254,232,138,0.85),
    inset 0 0 14px -4px rgba(212,161,63,0.65),
    0 0 0 2px rgba(212,161,63,0.78),
    0 0 0 3.2px rgba(122,79,18,0.85),
    0 0 22px 4px rgba(212,161,63,0.55),
    0 0 38px 7px rgba(122,79,18,0.32);
  animation: fc-chc-pulse 5.6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-chancellery:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,184,1),
    inset 0 0 18px -3px rgba(254,232,138,0.92),
    0 0 0 2.5px rgba(254,232,138,1),
    0 0 0 4px rgba(122,79,18,1),
    0 0 32px 6px rgba(212,161,63,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-chancellery .fc-chc-rotor { animation: fc-chc-rotate 60s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-chancellery .fc-chc-pulse { animation: fc-chc-tick 12s steps(12) infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-chancellery .fc-chc-eagle { animation: fc-chc-eagle-breath 7s ease-in-out infinite; }
@keyframes fc-chc-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.13); }
}
@keyframes fc-chc-rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
@keyframes fc-chc-tick {
  0%   { transform: translate(0,0); }     8.3% { transform: translate(21,6); }
  16.6%{ transform: translate(36,21); }   25%  { transform: translate(42,42); }
  33.3%{ transform: translate(36,63); }   41.6%{ transform: translate(21,78); }
  50%  { transform: translate(0,84); }    58.3%{ transform: translate(-21,78); }
  66.6%{ transform: translate(-36,63); }  75%  { transform: translate(-42,42); }
  83.3%{ transform: translate(-36,21); }  91.6%{ transform: translate(-21,6); }
  100% { transform: translate(0,0); }
}
@keyframes fc-chc-eagle-breath {
  0%, 100% { transform: scale(1); filter: brightness(1); }
  50% { transform: scale(1.04); filter: brightness(1.12); }
}
.fc-encircle-size-xs.fc-encircle-chancellery .fc-chc-core,
.fc-encircle-size-sm.fc-encircle-chancellery .fc-chc-ticks,
.fc-encircle-size-sm.fc-encircle-chancellery .fc-chc-eagle { display: none; }

/* ──── A2 · STATEHOUSE — Capitol dome over slate-blue sky ──── */
.fc-encircle-shadow_chancellor.fc-encircle-statehouse .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #1e3a5f 0%, #050a14 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(255,250,240,0.78),
    inset 0 0 12px -3px rgba(150,170,200,0.42),
    0 0 0 2px rgba(192,184,168,0.78),
    0 0 0 3.2px rgba(46,68,96,0.85),
    0 0 22px 4px rgba(150,170,200,0.42),
    0 0 38px 7px rgba(46,68,96,0.28);
  animation: fc-sth-pulse 5.2s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-statehouse:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,250,240,1),
    inset 0 0 18px -3px rgba(180,200,220,0.95),
    0 0 0 2.5px rgba(255,250,240,1),
    0 0 0 4px rgba(46,68,96,1),
    0 0 32px 6px rgba(150,170,200,0.65);
}
.fc-encircle-shadow_chancellor.fc-encircle-statehouse .fc-sth-dome { animation: fc-sth-lift 7s ease-in-out infinite; transform-origin: 50px 70px; }
.fc-encircle-shadow_chancellor.fc-encircle-statehouse .fc-sth-stars { animation: fc-sth-twinkle 4s ease-in-out infinite; }
@keyframes fc-sth-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.12) saturate(1.15); }
}
@keyframes fc-sth-lift {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-1.5px); }
}
@keyframes fc-sth-twinkle {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.fc-encircle-size-xs.fc-encircle-statehouse .fc-sth-core,
.fc-encircle-size-sm.fc-encircle-statehouse .fc-sth-stars { display: none; }

/* ──── A3 · BASTILLE — Fortified rampart with torches ──── */
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #382f28 0%, #0a0604 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(160,144,128,0.78),
    inset 0 0 12px -3px rgba(60,40,20,0.62),
    0 0 0 2px rgba(92,80,70,0.85),
    0 0 0 3.2px rgba(26,18,14,1),
    0 0 22px 4px rgba(255,140,30,0.32),
    0 0 38px 7px rgba(160,40,0,0.28);
  animation: fc-bst-pulse 6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-bastille:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(220,200,160,1),
    inset 0 0 18px -3px rgba(160,80,20,0.85),
    0 0 0 2.5px rgba(160,144,128,1),
    0 0 0 4px rgba(26,18,14,1),
    0 0 32px 6px rgba(255,140,30,0.55);
}
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-bst-torch-1 { animation: fc-bst-flicker 1.3s steps(7) infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-bst-torch-2 { animation: fc-bst-flicker 1.1s steps(7) 0.3s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-bst-torch-3 { animation: fc-bst-flicker 1.5s steps(7) 0.7s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-bst-torch-4 { animation: fc-bst-flicker 1.2s steps(7) 0.5s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bastille .fc-bst-banner { animation: fc-bst-banner-ripple 11s ease-in-out infinite; transform-origin: 50px 52px; }
@keyframes fc-bst-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.08); }
}
@keyframes fc-bst-flicker {
  0%   { opacity: 0.95; transform: scale(1); }
  20%  { opacity: 0.65; transform: scale(0.92); }
  40%  { opacity: 1.05; transform: scale(1.08); }
  60%  { opacity: 0.75; transform: scale(0.96); }
  80%  { opacity: 0.95; transform: scale(1.02); }
  100% { opacity: 0.95; transform: scale(1); }
}
@keyframes fc-bst-banner-ripple {
  0%, 100% { transform: skewX(0deg); }
  50% { transform: skewX(-2deg); }
}
.fc-encircle-size-xs.fc-encircle-bastille .fc-bst-core,
.fc-encircle-size-sm.fc-encircle-bastille .fc-bst-banner,
.fc-encircle-size-sm.fc-encircle-bastille .fc-bst-torch-3,
.fc-encircle-size-sm.fc-encircle-bastille .fc-bst-torch-4 { display: none; }

/* ──── A4 · MINISTRY — Typewriter platen + serif glyphs ──── */
.fc-encircle-shadow_chancellor.fc-encircle-ministry .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #2a3a2a 0%, #0e1812 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(240,232,200,0.78),
    inset 0 0 12px -3px rgba(80,100,80,0.45),
    0 0 0 2px rgba(122,140,122,0.78),
    0 0 0 3.2px rgba(26,40,26,1),
    0 0 22px 4px rgba(200,184,128,0.32),
    0 0 38px 7px rgba(80,100,80,0.22);
  animation: fc-min-pulse 5.4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-ministry:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(240,232,200,1),
    inset 0 0 18px -3px rgba(200,184,128,0.92),
    0 0 0 2.5px rgba(240,232,200,1),
    0 0 0 4px rgba(26,40,26,1),
    0 0 32px 6px rgba(200,184,128,0.62);
}
.fc-encircle-shadow_chancellor.fc-encircle-ministry .fc-min-ribbon { animation: fc-min-platen 9s steps(8) infinite; transform-origin: 50px 50px; }
.fc-encircle-shadow_chancellor.fc-encircle-ministry .fc-min-ink { animation: fc-min-ink-ripple 13s ease-in-out infinite; transform-origin: 50px 80px; }
@keyframes fc-min-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.1) sepia(0.12); }
}
@keyframes fc-min-platen {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(45deg); }
}
@keyframes fc-min-ink-ripple {
  0%, 100% { transform: scaleX(1); opacity: 0.85; }
  50% { transform: scaleX(1.18); opacity: 1; }
}
.fc-encircle-size-xs.fc-encircle-ministry .fc-min-core,
.fc-encircle-size-sm.fc-encircle-ministry .fc-min-text,
.fc-encircle-size-sm.fc-encircle-ministry .fc-min-ribbon text { display: none; }

/* ──── B1 · OLIVE-BRANCH — Peace wreath ──── */
.fc-encircle-shadow_chancellor.fc-encircle-olive-branch .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #cbd2b8 0%, #5a6448 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(244,240,216,0.95),
    inset 0 0 14px -3px rgba(126,161,88,0.55),
    0 0 0 2px rgba(126,161,88,0.85),
    0 0 0 3.2px rgba(90,100,72,1),
    0 0 22px 4px rgba(180,200,140,0.55),
    0 0 38px 7px rgba(90,100,72,0.32);
  animation: fc-olv-pulse 6.5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-olive-branch:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,250,235,1),
    inset 0 0 18px -3px rgba(180,200,140,0.92),
    0 0 0 2.5px rgba(244,240,216,1),
    0 0 0 4px rgba(90,100,72,1),
    0 0 32px 6px rgba(180,200,140,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-olive-branch .fc-olv-leaves-l { animation: fc-olv-rustle 11s ease-in-out infinite; transform-origin: 30px 78px; }
.fc-encircle-shadow_chancellor.fc-encircle-olive-branch .fc-olv-leaves-r { animation: fc-olv-rustle 11s ease-in-out 5.5s infinite; transform-origin: 70px 78px; }
.fc-encircle-shadow_chancellor.fc-encircle-olive-branch .fc-olv-dove { animation: fc-olv-dove-breath 6s ease-in-out infinite; transform-origin: 50px 56px; }
@keyframes fc-olv-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.1); }
}
@keyframes fc-olv-rustle {
  0%, 92%, 100% { transform: rotate(0deg); }
  94% { transform: rotate(3deg); }
  96% { transform: rotate(-2deg); }
  98% { transform: rotate(1deg); }
}
@keyframes fc-olv-dove-breath {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}
.fc-encircle-size-xs.fc-encircle-olive-branch .fc-olv-core,
.fc-encircle-size-sm.fc-encircle-olive-branch .fc-olv-dove { display: none; }

/* ──── B2 · CROSS-SHIELD — Humanitarian red cross ──── */
.fc-encircle-shadow_chancellor.fc-encircle-cross-shield .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #e8eef4 0%, #8a9bab 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(255,255,255,0.92),
    inset 0 0 14px -3px rgba(231,42,42,0.42),
    0 0 0 2px rgba(231,42,42,0.85),
    0 0 0 3.2px rgba(15,200,208,0.78),
    0 0 22px 4px rgba(231,42,42,0.45),
    0 0 38px 7px rgba(15,200,208,0.28);
  animation: fc-csh-pulse 4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-cross-shield:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,255,255,1),
    inset 0 0 18px -3px rgba(231,42,42,0.62),
    0 0 0 2.5px rgba(231,42,42,1),
    0 0 0 4px rgba(15,200,208,1),
    0 0 32px 6px rgba(231,42,42,0.65);
}
.fc-encircle-shadow_chancellor.fc-encircle-cross-shield .fc-csh-cross {
  animation: fc-csh-heartbeat 4s ease-in-out infinite;
  transform-origin: 50px 50px;
}
@keyframes fc-csh-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.08); }
}
@keyframes fc-csh-heartbeat {
  0%, 35%, 100% { transform: scale(1); }
  10%, 25% { transform: scale(1.08); }
  15%, 30% { transform: scale(1.05); }
}
.fc-encircle-size-xs.fc-encircle-cross-shield .fc-csh-core { display: none; }

/* ──── B3 · LIGHTHOUSE — Beacon tower with rotating cyan beam ──── */
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #03101a 0%, #000508 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(15,200,208,0.78),
    inset 0 0 14px -3px rgba(15,200,208,0.42),
    0 0 0 2px rgba(15,200,208,0.62),
    0 0 0 3.2px rgba(58,72,88,1),
    0 0 22px 4px rgba(180,240,255,0.42),
    0 0 38px 7px rgba(15,200,208,0.28);
  animation: fc-lhs-pulse 5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(180,240,255,1),
    inset 0 0 18px -3px rgba(15,200,208,0.85),
    0 0 0 2.5px rgba(15,200,208,1),
    0 0 0 4px rgba(58,72,88,1),
    0 0 32px 6px rgba(180,240,255,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beam-rotor { animation: fc-lhs-beam 10s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle { animation: fc-lhs-beacon-pulse 10s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(1) { animation-delay: 0s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(2) { animation-delay: 0.83s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(3) { animation-delay: 1.66s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(4) { animation-delay: 2.5s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(5) { animation-delay: 3.33s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(6) { animation-delay: 4.16s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(7) { animation-delay: 5s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(8) { animation-delay: 5.83s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(9) { animation-delay: 6.66s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(10) { animation-delay: 7.5s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(11) { animation-delay: 8.33s; }
.fc-encircle-shadow_chancellor.fc-encircle-lighthouse .fc-lhs-beacons circle:nth-child(12) { animation-delay: 9.16s; }
@keyframes fc-lhs-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.12) saturate(1.2); }
}
@keyframes fc-lhs-beam {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes fc-lhs-beacon-pulse {
  0%, 4%, 100% { opacity: 0.45; r: 0.9; }
  2% { opacity: 1; r: 1.8; }
}
.fc-encircle-size-xs.fc-encircle-lighthouse .fc-lhs-core,
.fc-encircle-size-sm.fc-encircle-lighthouse .fc-lhs-beacons { display: none; }

/* ──── B4 · COMMONS — Interlocking rings ──── */
.fc-encircle-shadow_chancellor.fc-encircle-commons .fc-encircle-frame {
  background: linear-gradient(135deg, #1a3030 0%, #0a1818 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(180,240,200,0.62),
    inset 0 0 14px -3px rgba(58,143,204,0.42),
    0 0 0 2px rgba(180,240,200,0.55),
    0 0 0 3.2px rgba(26,48,48,1),
    0 0 22px 4px rgba(58,170,72,0.42),
    0 0 38px 7px rgba(58,143,204,0.28);
  animation: fc-cmn-pulse 5.4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-commons:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(220,255,230,1),
    inset 0 0 18px -3px rgba(58,170,72,0.85),
    0 0 0 2.5px rgba(180,240,200,1),
    0 0 0 4px rgba(26,48,48,1),
    0 0 32px 6px rgba(58,143,204,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-commons .fc-cmn-rings { animation: fc-cmn-breathe 5.4s ease-in-out infinite; transform-origin: 50px 50px; }
.fc-encircle-shadow_chancellor.fc-encircle-commons .fc-cmn-arrows { animation: fc-cmn-arrows 13s ease-in-out infinite; transform-origin: 50px 50px; }
@keyframes fc-cmn-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.12) saturate(1.18); }
}
@keyframes fc-cmn-breathe {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.05); }
}
@keyframes fc-cmn-arrows {
  0%, 88%, 100% { transform: translate(0,0); opacity: 0.6; }
  92% { transform: scale(1.15); opacity: 1; }
  96% { transform: scale(1); opacity: 0.85; }
}
.fc-encircle-size-xs.fc-encircle-commons .fc-cmn-core,
.fc-encircle-size-sm.fc-encircle-commons .fc-cmn-arrows { display: none; }

/* ──── C1 · MOONSHOT — Rocket with chromatic trails ──── */
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-encircle-frame {
  background: radial-gradient(ellipse at 30% 70%, #5e0a5e 0%, #1a0238 60%, #0a1a4a 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(255,180,40,0.95),
    inset 0 0 14px -3px rgba(255,40,180,0.62),
    0 0 0 2px rgba(255,40,180,0.78),
    0 0 0 3.2px rgba(58,10,90,1),
    0 0 26px 5px rgba(255,180,40,0.55),
    0 0 46px 9px rgba(255,40,180,0.38);
  animation: fc-mns-pulse 4.5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-moonshot:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,184,1),
    inset 0 0 18px -3px rgba(255,40,180,0.92),
    0 0 0 2.5px rgba(255,180,40,1),
    0 0 0 4px rgba(58,10,90,1),
    0 0 38px 8px rgba(255,40,180,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-mns-rocket { animation: fc-mns-thrust 4.5s ease-in-out infinite; transform-box: fill-box; transform-origin: 0 0; }
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-mns-trails { animation: fc-mns-trail-shimmer 4s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-mns-stars circle { animation: fc-mns-twinkle 3s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-mns-stars circle:nth-child(2n) { animation-delay: 1.5s; }
.fc-encircle-shadow_chancellor.fc-encircle-moonshot .fc-mns-text { animation: fc-mns-text-scroll 18s linear infinite; transform-origin: 50px 50px; }
@keyframes fc-mns-pulse {
  0%, 100% { filter: brightness(1) saturate(1.1); }
  50% { filter: brightness(1.18) saturate(1.4); }
}
@keyframes fc-mns-thrust {
  0%, 100% { transform: translate(50px,50px) rotate(-45deg) scale(1); filter: brightness(1); }
  50% { transform: translate(50px,50px) rotate(-45deg) scale(1.08); filter: brightness(1.2); }
}
@keyframes fc-mns-trail-shimmer {
  0%, 100% { opacity: 0.78; }
  50% { opacity: 1; }
}
@keyframes fc-mns-twinkle {
  0%, 100% { opacity: 0.45; }
  50% { opacity: 1; }
}
@keyframes fc-mns-text-scroll {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.fc-encircle-size-xs.fc-encircle-moonshot .fc-mns-core,
.fc-encircle-size-sm.fc-encircle-moonshot .fc-mns-text,
.fc-encircle-size-sm.fc-encircle-moonshot .fc-mns-stars { display: none; }

/* ──── C2 · DIAMOND-HANDS — Faceted shards radiating ──── */
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #dceaf4 0%, #1a3858 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(255,255,255,0.95),
    inset 0 0 14px -3px rgba(120,200,255,0.62),
    0 0 0 2px rgba(255,255,255,0.85),
    0 0 0 3.2px rgba(26,56,88,1),
    /* Chromatic micro-rim */
    0 0 0 4px rgba(255,80,160,0.32),
    0 0 0 5px rgba(15,200,255,0.32),
    0 0 26px 5px rgba(180,228,255,0.55),
    0 0 46px 9px rgba(120,200,255,0.38);
  animation: fc-dmh-pulse 5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,255,255,1),
    inset 0 0 18px -3px rgba(180,228,255,0.92),
    0 0 0 2.5px rgba(255,255,255,1),
    0 0 0 4px rgba(255,80,160,0.55),
    0 0 0 5px rgba(15,200,255,0.55),
    0 0 38px 8px rgba(180,228,255,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shards { animation: fc-dmh-rotate 24s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-1 { animation: fc-dmh-twinkle 9s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-2 { animation: fc-dmh-twinkle 9s ease-in-out 1.5s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-3 { animation: fc-dmh-twinkle 9s ease-in-out 3s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-4 { animation: fc-dmh-twinkle 9s ease-in-out 4.5s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-5 { animation: fc-dmh-twinkle 9s ease-in-out 6s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-shard-6 { animation: fc-dmh-twinkle 9s ease-in-out 7.5s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-diamond-hands .fc-dmh-fists { animation: fc-dmh-clench 11s ease-in-out infinite; transform-origin: 50px 50px; }
@keyframes fc-dmh-pulse {
  0%, 100% { filter: brightness(1) saturate(1.15); }
  50% { filter: brightness(1.18) saturate(1.35); }
}
@keyframes fc-dmh-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes fc-dmh-twinkle {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.55) saturate(1.5); }
}
@keyframes fc-dmh-clench {
  0%, 88%, 100% { transform: scale(1); }
  92% { transform: scale(0.92); }
  96% { transform: scale(1.08); }
}
.fc-encircle-size-xs.fc-encircle-diamond-hands .fc-dmh-core,
.fc-encircle-size-sm.fc-encircle-diamond-hands .fc-dmh-fists { display: none; }

/* ──── C3 · CHAD-FROG — Stylized cartoon frog face ──── */
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #3a6428 0%, #0a1808 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(156,200,72,0.85),
    inset 0 0 14px -3px rgba(58,84,24,0.62),
    0 0 0 2px rgba(126,170,72,0.78),
    0 0 0 3.2px rgba(26,48,8,1),
    0 0 22px 4px rgba(156,200,72,0.42),
    0 0 38px 7px rgba(58,84,24,0.28);
  animation: fc-cfg-pulse 5.6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(220,255,160,1),
    inset 0 0 18px -3px rgba(156,200,72,0.92),
    0 0 0 2.5px rgba(156,200,72,1),
    0 0 0 4px rgba(26,48,8,1),
    0 0 32px 6px rgba(156,200,72,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-cfg-eye-l,
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-cfg-eye-r { animation: fc-cfg-wink 7s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-cfg-eye-r { animation-delay: 3.5s; }
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-cfg-monocle { animation: fc-cfg-glint 11s ease-in-out infinite; transform-origin: 64px 36px; }
.fc-encircle-shadow_chancellor.fc-encircle-chad-frog .fc-cfg-hand { animation: fc-cfg-ok 22s ease-in-out infinite; transform-box: fill-box; }
@keyframes fc-cfg-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.12) saturate(1.18); }
}
@keyframes fc-cfg-wink {
  0%, 94%, 100% { transform: scaleY(1); }
  95%, 97% { transform: scaleY(0.05); }
}
@keyframes fc-cfg-glint {
  0%, 92%, 100% { filter: brightness(1); }
  94%, 96% { filter: brightness(2) drop-shadow(0 0 4px #fde04a); }
}
@keyframes fc-cfg-ok {
  0%, 88%, 100% { transform: scale(1) translate(0,0); opacity: 1; }
  92% { transform: scale(1.4) translate(-2px,-2px); opacity: 1; }
  96% { transform: scale(1.2) translate(-1px,-1px); opacity: 0.85; }
}
.fc-encircle-size-xs.fc-encircle-chad-frog .fc-cfg-core,
.fc-encircle-size-sm.fc-encircle-chad-frog .fc-cfg-monocle,
.fc-encircle-size-sm.fc-encircle-chad-frog .fc-cfg-hand { display: none; }

/* ──── C4 · PIXEL-SHRINE — 8-bit altar with floating coin ──── */
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine .fc-encircle-frame {
  background: linear-gradient(180deg, #3a1a5a 0%, #10042a 100%);
  box-shadow:
    inset 0 0 0 1.4px rgba(240,200,40,0.85),
    inset 0 0 14px -3px rgba(160,64,200,0.62),
    /* Pixel-chunky outer rim */
    0 0 0 2px rgba(240,200,40,0.85),
    0 0 0 3.2px rgba(58,28,90,1),
    0 0 0 4px rgba(160,64,200,0.62),
    0 0 22px 4px rgba(240,200,40,0.42),
    0 0 38px 7px rgba(160,64,200,0.32);
  animation: fc-pxs-pulse 4.8s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,184,1),
    inset 0 0 18px -3px rgba(160,64,200,0.92),
    0 0 0 2.5px rgba(240,200,40,1),
    0 0 0 4px rgba(160,64,200,1),
    0 0 32px 6px rgba(240,200,40,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine .fc-pxs-coin { animation: fc-pxs-coin-spin 1.6s steps(4, end) infinite, fc-pxs-coin-float 2.4s ease-in-out infinite; transform-origin: 50px 36px; }
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine .fc-pxs-flame-1 { animation: fc-pxs-flame 0.4s steps(2) infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine .fc-pxs-flame-2 { animation: fc-pxs-flame 0.4s steps(2) 0.2s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-pixel-shrine .fc-pxs-sparkles { animation: fc-pxs-sparkle 1.2s steps(2) infinite; }
@keyframes fc-pxs-pulse {
  0%, 100% { filter: brightness(1) hue-rotate(0deg); }
  50% { filter: brightness(1.18) hue-rotate(10deg); }
}
@keyframes fc-pxs-coin-spin {
  0%   { transform: scaleX(1); }
  25%  { transform: scaleX(0.3); }
  50%  { transform: scaleX(-1); }
  75%  { transform: scaleX(-0.3); }
  100% { transform: scaleX(1); }
}
@keyframes fc-pxs-coin-float {
  0%, 100% { translate: 0 0; }
  50% { translate: 0 -2px; }
}
@keyframes fc-pxs-flame {
  0%, 100% { transform: translateX(0); opacity: 1; }
  50% { transform: translateX(0.5px); opacity: 0.75; }
}
@keyframes fc-pxs-sparkle {
  0%, 100% { opacity: 0.85; }
  50% { opacity: 0; }
}
.fc-encircle-size-xs.fc-encircle-pixel-shrine .fc-pxs-core,
.fc-encircle-size-sm.fc-encircle-pixel-shrine .fc-pxs-sparkles { display: none; }

/* ──── D1 · SAVANNA — African horizon ──── */
.fc-encircle-shadow_chancellor.fc-encircle-savanna .fc-encircle-frame {
  background: linear-gradient(180deg, #3a1808 0%, #c84818 30%, #f0a048 60%, #8a3408 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(254,224,136,0.92),
    inset 0 0 14px -3px rgba(200,72,24,0.62),
    0 0 0 2px rgba(254,224,136,0.78),
    0 0 0 3.2px rgba(58,20,8,1),
    0 0 24px 4px rgba(240,160,72,0.55),
    0 0 42px 8px rgba(200,72,24,0.42);
  animation: fc-svn-pulse 6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-savanna:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,250,200,1),
    inset 0 0 18px -3px rgba(240,160,72,0.92),
    0 0 0 2.5px rgba(254,224,136,1),
    0 0 0 4px rgba(58,20,8,1),
    0 0 36px 7px rgba(240,160,72,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-savanna .fc-svn-bird-1 { animation: fc-svn-bird 22s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-savanna .fc-svn-bird-2 { animation: fc-svn-bird 22s linear -7s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-savanna .fc-svn-bird-3 { animation: fc-svn-bird 22s linear -14s infinite; }
@keyframes fc-svn-pulse {
  0%, 100% { filter: brightness(1) saturate(1.15); }
  50% { filter: brightness(1.12) saturate(1.35); }
}
@keyframes fc-svn-bird {
  0%   { transform: translate(-30px, 0); opacity: 0; }
  10%, 90% { opacity: 0.85; }
  100% { transform: translate(30px, -4px); opacity: 0; }
}
.fc-encircle-size-xs.fc-encircle-savanna .fc-svn-core,
.fc-encircle-size-sm.fc-encircle-savanna .fc-svn-birds { display: none; }

/* ──── D2 · ANDES — Inca textile with condor ──── */
.fc-encircle-shadow_chancellor.fc-encircle-andes .fc-encircle-frame {
  background: linear-gradient(180deg, #1c2848 0%, #5a4828 50%, #c87828 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(254,224,136,0.85),
    inset 0 0 14px -3px rgba(200,120,40,0.62),
    0 0 0 2px rgba(200,120,40,0.78),
    0 0 0 3.2px rgba(58,24,8,1),
    0 0 24px 4px rgba(254,224,136,0.45),
    0 0 42px 8px rgba(200,120,40,0.32);
  animation: fc-and-pulse 5.6s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-andes:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,200,1),
    inset 0 0 18px -3px rgba(254,224,136,0.85),
    0 0 0 2.5px rgba(254,224,136,1),
    0 0 0 4px rgba(58,24,8,1),
    0 0 36px 7px rgba(200,120,40,0.72);
}
.fc-encircle-shadow_chancellor.fc-encircle-andes .fc-and-condor { animation: fc-and-condor-glide 20s ease-in-out infinite; transform-origin: 50px 32px; }
.fc-encircle-shadow_chancellor.fc-encircle-andes .fc-and-band-top { animation: fc-and-band 7s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-andes .fc-and-band-bot { animation: fc-and-band 7s ease-in-out 3.5s infinite; }
@keyframes fc-and-pulse {
  0%, 100% { filter: brightness(1) saturate(1.1); }
  50% { filter: brightness(1.12) saturate(1.25); }
}
@keyframes fc-and-condor-glide {
  0%   { transform: translateX(-22px) scaleX(1); opacity: 0; }
  15%, 85% { opacity: 0.92; }
  50%  { transform: translateX(0) scaleX(1.05); }
  100% { transform: translateX(22px) scaleX(1); opacity: 0; }
}
@keyframes fc-and-band {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.18); }
}
.fc-encircle-size-xs.fc-encircle-andes .fc-and-core,
.fc-encircle-size-sm.fc-encircle-andes .fc-and-condor { display: none; }

/* ──── D3 · LIBERTY — 7-point crown + torch ──── */
.fc-encircle-shadow_chancellor.fc-encircle-liberty .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #1a3838 0%, #020808 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(126,184,168,0.85),
    inset 0 0 14px -3px rgba(58,104,104,0.62),
    0 0 0 2px rgba(126,184,168,0.78),
    0 0 0 3.2px rgba(10,32,32,1),
    /* Torchlight halo */
    0 0 24px 4px rgba(254,224,74,0.42),
    0 0 42px 8px rgba(240,140,28,0.28);
  animation: fc-lib-pulse 5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-liberty:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(180,224,200,1),
    inset 0 0 18px -3px rgba(254,224,74,0.62),
    0 0 0 2.5px rgba(126,184,168,1),
    0 0 0 4px rgba(10,32,32,1),
    0 0 36px 7px rgba(254,224,74,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-liberty .fc-lib-flame { animation: fc-lib-flame-flicker 1.2s steps(5) infinite; transform-origin: 50px 50px; }
.fc-encircle-shadow_chancellor.fc-encircle-liberty .fc-lib-crown { animation: fc-lib-crown-glint 13s ease-in-out infinite; }
@keyframes fc-lib-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.18) saturate(1.18); }
}
@keyframes fc-lib-flame-flicker {
  0%   { transform: scale(1) skewX(0deg); }
  20%  { transform: scale(1.08, 0.95) skewX(-3deg); }
  40%  { transform: scale(0.95, 1.05) skewX(2deg); }
  60%  { transform: scale(1.06, 0.92) skewX(-1deg); }
  80%  { transform: scale(0.98, 1.02) skewX(1deg); }
  100% { transform: scale(1) skewX(0deg); }
}
@keyframes fc-lib-crown-glint {
  0%, 92%, 100% { filter: brightness(1); }
  94%, 96% { filter: brightness(1.5) drop-shadow(0 0 4px #fde88a); }
}
.fc-encircle-size-xs.fc-encircle-liberty .fc-lib-core,
.fc-encircle-size-sm.fc-encircle-liberty .fc-lib-crown { display: none; }

/* ──── D4 · OUTBACK — Terracotta with abstract dots ──── */
.fc-encircle-shadow_chancellor.fc-encircle-outback .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #e8743a 0%, #a8421a 50%, #3a1408 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(254,224,136,0.85),
    inset 0 0 14px -3px rgba(168,66,26,0.62),
    0 0 0 2px rgba(232,116,58,0.78),
    0 0 0 3.2px rgba(58,20,8,1),
    0 0 24px 4px rgba(254,224,136,0.45),
    0 0 42px 8px rgba(168,66,26,0.32);
  animation: fc-otb-pulse 5.4s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-outback:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,200,1),
    inset 0 0 18px -3px rgba(232,116,58,0.85),
    0 0 0 2.5px rgba(254,224,136,1),
    0 0 0 4px rgba(58,20,8,1),
    0 0 36px 7px rgba(232,116,58,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-outback .fc-otb-dots circle { animation: fc-otb-breathe 6s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-outback .fc-otb-dots circle:nth-child(odd) { animation-delay: 3s; }
.fc-encircle-shadow_chancellor.fc-encircle-outback .fc-otb-leaf { animation: fc-otb-leaf-shift 17s ease-in-out infinite; }
@keyframes fc-otb-pulse {
  0%, 100% { filter: brightness(1) saturate(1.1); }
  50% { filter: brightness(1.12) saturate(1.3); }
}
@keyframes fc-otb-breathe {
  0%, 100% { filter: brightness(1); opacity: 0.92; }
  50% { filter: brightness(1.32); opacity: 1; }
}
@keyframes fc-otb-leaf-shift {
  0%, 100% { transform: rotate(0deg); }
  50% { transform: rotate(4deg); }
}
.fc-encircle-size-xs.fc-encircle-outback .fc-otb-core,
.fc-encircle-size-sm.fc-encircle-outback .fc-otb-leaf { display: none; }

/* ──── D5 · ALPINE — Glacier peaks with edelweiss ──── */
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-encircle-frame {
  background: radial-gradient(circle at 50% 40%, #dceaf4 0%, #a8c8e0 50%, #586878 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(255,255,255,0.95),
    inset 0 0 14px -3px rgba(168,200,224,0.62),
    0 0 0 2px rgba(220,234,244,0.85),
    0 0 0 3.2px rgba(88,104,120,1),
    0 0 24px 4px rgba(180,220,255,0.42),
    0 0 42px 8px rgba(88,104,120,0.32);
  animation: fc-alp-pulse 6.2s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-alpine:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,255,255,1),
    inset 0 0 18px -3px rgba(180,220,255,0.85),
    0 0 0 2.5px rgba(255,255,255,1),
    0 0 0 4px rgba(88,104,120,1),
    0 0 36px 7px rgba(180,220,255,0.78);
}
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-snow-1 { animation: fc-alp-snowfall 14s linear infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-snow-2 { animation: fc-alp-snowfall 14s linear -2.8s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-snow-3 { animation: fc-alp-snowfall 14s linear -5.6s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-snow-4 { animation: fc-alp-snowfall 14s linear -8.4s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-snow-5 { animation: fc-alp-snowfall 14s linear -11.2s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-alpine .fc-alp-edelweiss { animation: fc-alp-edelweiss-pulse 5s ease-in-out infinite; }
@keyframes fc-alp-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.08) hue-rotate(-4deg); }
}
@keyframes fc-alp-snowfall {
  0%   { transform: translateY(-12px) translateX(0); opacity: 0; }
  10%  { opacity: 0.92; }
  90%  { opacity: 0.55; }
  100% { transform: translateY(28px) translateX(2px); opacity: 0; }
}
@keyframes fc-alp-edelweiss-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.18) drop-shadow(0 0 4px rgba(255,255,255,0.65)); }
}
.fc-encircle-size-xs.fc-encircle-alpine .fc-alp-core,
.fc-encircle-size-sm.fc-encircle-alpine .fc-alp-snow { display: none; }

/* ──── E1 · BULLION-VAULT — Heavy vault door ──── */
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-encircle-frame {
  background: radial-gradient(circle at 50% 50%, #48504c 0%, #0a0c10 100%);
  box-shadow:
    inset 0 0 0 1.5px rgba(254,232,138,0.95),
    inset 0 0 14px -3px rgba(212,161,63,0.62),
    0 0 0 2px rgba(212,161,63,0.92),
    0 0 0 3.2px rgba(26,28,24,1),
    0 0 24px 4px rgba(254,232,138,0.55),
    0 0 42px 8px rgba(122,79,18,0.42);
  animation: fc-bvt-pulse 5s ease-in-out infinite;
}
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,244,184,1),
    inset 0 0 18px -3px rgba(254,232,138,0.95),
    0 0 0 2.5px rgba(254,232,138,1),
    0 0 0 4px rgba(26,28,24,1),
    0 0 36px 7px rgba(254,232,138,0.85);
}
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-wheel { animation: fc-bvt-rotate 9s steps(9, end) infinite; transform-origin: 50px 50px; }
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-bolts polygon { animation: fc-bvt-glint 13s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-bolts polygon:nth-child(2n) { animation-delay: 6.5s; }
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-ingot-1 { animation: fc-bvt-shimmer 13s ease-in-out infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-ingot-2 { animation: fc-bvt-shimmer 13s ease-in-out 4.3s infinite; }
.fc-encircle-shadow_chancellor.fc-encircle-bullion-vault .fc-bvt-ingot-3 { animation: fc-bvt-shimmer 13s ease-in-out 8.6s infinite; }
@keyframes fc-bvt-pulse {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.12) saturate(1.2); }
}
@keyframes fc-bvt-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
@keyframes fc-bvt-glint {
  0%, 92%, 100% { filter: brightness(1); }
  94%, 96% { filter: brightness(1.5) drop-shadow(0 0 3px #fde88a); }
}
@keyframes fc-bvt-shimmer {
  0%, 100% { filter: brightness(1); }
  50% { filter: brightness(1.45) drop-shadow(0 0 2px #fde88a); }
}
.fc-encircle-size-xs.fc-encircle-bullion-vault .fc-bvt-core,
.fc-encircle-size-sm.fc-encircle-bullion-vault .fc-bvt-bolts { display: none; }

/* ════════════════════════════════════════════════════════════════════
   §pass67 (2026-05-23) — 8 NEW REGISTRY OVERLAYS (broken-machine axis)
   ════════════════════════════════════════════════════════════════════ */

/* Shared overlay scaffold */
.fc-rd, .fc-mf, .fc-rg, .fc-sh, .fc-bn, .fc-sd, .fc-kd, .fc-fz {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  overflow: hidden;
  pointer-events: none;
  z-index: 4;
}
.fc-rd-svg, .fc-mf-svg, .fc-rg-svg, .fc-sh-svg,
.fc-bn-svg, .fc-sd-svg, .fc-kd-svg, .fc-fz-svg {
  width: 100%; height: 100%; display: block;
}

/* ──── F1 · REDACTION — Classified censorship bars ──── */
.fc-overlay-redaction .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,40,40,0.55),
    0 0 0 2px rgba(0,0,0,0.85),
    0 0 14px 2px rgba(255,40,40,0.32);
}
.fc-overlay-redaction:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,40,40,0.85),
    0 0 0 2.5px rgba(0,0,0,1),
    0 0 22px 4px rgba(255,40,40,0.62);
}
.fc-overlay-redaction .fc-encircle-avatar-img { filter: saturate(0.65) contrast(1.1); }
.fc-rd-bar-1 { animation: fc-rd-slide-1 14s ease-in-out infinite; }
.fc-rd-bar-2 { animation: fc-rd-slide-2 16s ease-in-out infinite; }
.fc-rd-bar-3 { animation: fc-rd-slide-3 15s ease-in-out infinite; }
.fc-rd-bar-4 { animation: fc-rd-slide-4 17s ease-in-out infinite; }
.fc-rd-stamp { animation: fc-rd-stamp 14s ease-in-out infinite; }
@keyframes fc-rd-slide-1 { 0%, 12% { transform: translateX(0); } 16% { transform: translateX(140px); } 24% { transform: translateX(140px); } 28%, 100% { transform: translateX(0); } }
@keyframes fc-rd-slide-2 { 0%, 30% { transform: translateX(0); } 34% { transform: translateX(140px); } 42% { transform: translateX(140px); } 46%, 100% { transform: translateX(0); } }
@keyframes fc-rd-slide-3 { 0%, 50% { transform: translateX(0); } 54% { transform: translateX(140px); } 62% { transform: translateX(140px); } 66%, 100% { transform: translateX(0); } }
@keyframes fc-rd-slide-4 { 0%, 70% { transform: translateX(0); } 74% { transform: translateX(140px); } 82% { transform: translateX(140px); } 86%, 100% { transform: translateX(0); } }
@keyframes fc-rd-stamp {
  0%, 14%, 26%, 100% { fill: rgba(255,40,40,0); transform: rotate(-15deg) scale(1); }
  16%, 20% { fill: rgba(255,40,40,0.95); transform: rotate(-15deg) scale(1.15); }
  22%, 24% { fill: rgba(255,40,40,0.65); transform: rotate(-15deg) scale(1); }
}

/* ──── F2 · MANIFOLD — Overheating engine ──── */
.fc-overlay-manifold .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,140,40,0.62),
    0 0 0 2px rgba(60,28,8,0.85),
    0 0 18px 3px rgba(255,140,40,0.42);
}
.fc-overlay-manifold:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,180,40,0.85),
    0 0 0 2.5px rgba(60,28,8,1),
    0 0 28px 5px rgba(255,140,40,0.78);
}
.fc-overlay-manifold .fc-encircle-avatar-img { filter: contrast(1.05) brightness(0.95); }
.fc-mf-temp { animation: fc-mf-temp-climb 11s ease-in-out infinite; }
.fc-mf-jet-n ellipse { animation: fc-mf-puff-n 11s ease-in-out infinite; }
.fc-mf-jet-n ellipse:nth-child(2) { animation-delay: 0.15s; }
.fc-mf-jet-n ellipse:nth-child(3) { animation-delay: 0.3s; }
.fc-mf-jet-e ellipse { animation: fc-mf-puff-e 11s ease-in-out 1.8s infinite; }
.fc-mf-jet-e ellipse:nth-child(2) { animation-delay: 2s; }
.fc-mf-jet-sw ellipse { animation: fc-mf-puff-sw 11s ease-in-out 4s infinite; }
.fc-mf-jet-sw ellipse:nth-child(2) { animation-delay: 4.2s; }
.fc-mf-bar { animation: fc-mf-bar-climb 11s ease-in-out infinite; }
@keyframes fc-mf-temp-climb {
  0%, 70%, 100% { fill: #ff7838; }
  72%, 85% { fill: #ff3838; }
}
@keyframes fc-mf-puff-n {
  0%, 64%, 100% { opacity: 0; transform: translateY(0); }
  66% { opacity: 0.85; }
  78% { opacity: 0; transform: translateY(-8px); }
}
@keyframes fc-mf-puff-e {
  0%, 64%, 100% { opacity: 0; transform: translateX(0); }
  66% { opacity: 0.85; }
  78% { opacity: 0; transform: translateX(8px); }
}
@keyframes fc-mf-puff-sw {
  0%, 64%, 100% { opacity: 0; transform: translate(0,0); }
  66% { opacity: 0.85; }
  78% { opacity: 0; transform: translate(-8px,8px); }
}
@keyframes fc-mf-bar-climb {
  0%, 100% { width: 0; }
  50% { width: 32px; }
}

/* ──── F3 · TEAR-OUT (id 'rugpull') — fibers tearing ──── */
.fc-overlay-rugpull .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,80,80,0.62),
    0 0 0 2px rgba(254,224,74,0.62),
    0 0 0 3.2px rgba(60,8,8,1),
    0 0 18px 3px rgba(255,80,80,0.42);
}
.fc-overlay-rugpull:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,120,120,0.85),
    0 0 0 2.5px rgba(254,224,74,0.85),
    0 0 0 4px rgba(60,8,8,1),
    0 0 28px 5px rgba(255,80,80,0.78);
}
.fc-overlay-rugpull .fc-encircle-avatar-img { filter: contrast(1.12) saturate(0.92); }
.fc-rg-thread-1, .fc-rg-thread-2, .fc-rg-thread-3, .fc-rg-thread-4,
.fc-rg-thread-5, .fc-rg-thread-6, .fc-rg-thread-7, .fc-rg-thread-8 { animation: fc-rg-tear 17s ease-out infinite; }
.fc-rg-thread-2 { animation-delay: 0.04s; }
.fc-rg-thread-3 { animation-delay: 0.08s; }
.fc-rg-thread-4 { animation-delay: 0.12s; }
.fc-rg-thread-5 { animation-delay: 0.16s; }
.fc-rg-thread-6 { animation-delay: 0.2s; }
.fc-rg-thread-7 { animation-delay: 0.24s; }
.fc-rg-thread-8 { animation-delay: 0.28s; }
.fc-rg-gg { animation: fc-rg-gg 17s ease-in-out infinite; }
@keyframes fc-rg-tear {
  0%, 70%, 100% { opacity: 0; stroke-dashoffset: 60; stroke-dasharray: 60 60; }
  72% { opacity: 0.85; stroke-dashoffset: 0; }
  82% { opacity: 0.45; }
  85% { opacity: 0; }
}
@keyframes fc-rg-gg {
  0%, 70%, 100% { fill: rgba(255,80,80,0); transform: scale(1); }
  74%, 80% { fill: rgba(255,80,80,0.85); transform: scale(1.1); }
  85% { fill: rgba(255,80,80,0); transform: scale(1); }
}

/* ──── F4 · SHILLING — Fake notification bursts ──── */
.fc-overlay-shilling .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,64,184,0.62),
    0 0 0 2px rgba(254,224,74,0.55),
    0 0 0 3.2px rgba(60,8,80,1),
    0 0 18px 3px rgba(255,64,184,0.42);
}
.fc-overlay-shilling:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,180,220,0.85),
    0 0 0 2.5px rgba(254,224,74,0.85),
    0 0 0 4px rgba(60,8,80,1),
    0 0 28px 5px rgba(255,64,184,0.78);
}
.fc-overlay-shilling .fc-encircle-avatar-img { filter: saturate(1.18); }
.fc-sh-b-1 { animation: fc-sh-bubble 18s ease-in-out infinite; transform-origin: 17px 18.5px; }
.fc-sh-b-2 { animation: fc-sh-bubble 18s ease-in-out 0.4s infinite; transform-origin: 83px 24.5px; }
.fc-sh-b-3 { animation: fc-sh-bubble 18s ease-in-out 0.8s infinite; transform-origin: 86px 66.5px; }
.fc-sh-b-4 { animation: fc-sh-bubble 18s ease-in-out 1.2s infinite; transform-origin: 26px 72.5px; }
.fc-sh-b-5 { animation: fc-sh-bubble 18s ease-in-out 1.6s infinite; transform-origin: 50px 10.5px; }
@keyframes fc-sh-bubble {
  0%, 78%, 100% { opacity: 0; transform: scale(0.5); }
  82% { opacity: 1; transform: scale(1.18); }
  86% { opacity: 1; transform: scale(1); }
  94% { opacity: 0.45; transform: scale(0.9) translateY(-4px); }
  98% { opacity: 0; transform: scale(0.7) translateY(-8px); }
}

/* ──── F5 · BROWNOUT — Grid sag (frame dimming) ──── */
.fc-overlay-brownout .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,200,40,0.62),
    0 0 0 2px rgba(80,40,8,0.78),
    0 0 14px 2px rgba(255,200,40,0.32);
  animation: fc-bn-sag 19s ease-in-out infinite !important;
}
.fc-overlay-brownout:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,220,80,0.85),
    0 0 0 2.5px rgba(80,40,8,1),
    0 0 22px 4px rgba(255,200,40,0.62);
}
.fc-overlay-brownout .fc-encircle-avatar-img { filter: brightness(0.85) contrast(1.05); animation: fc-bn-img-sag 19s ease-in-out infinite; }
.fc-bn-flicker { animation: fc-bn-flicker 19s ease-in-out infinite; }
@keyframes fc-bn-sag {
  0%, 78%, 100% { filter: brightness(1); }
  82%, 90% { filter: brightness(0.42) saturate(0.7); }
}
@keyframes fc-bn-img-sag {
  0%, 78%, 100% { filter: brightness(0.85) contrast(1.05); }
  82%, 90% { filter: brightness(0.32) contrast(1.15) saturate(0.5); }
}
@keyframes fc-bn-flicker {
  0%, 78%, 100% { opacity: 0; }
  82%, 84% { opacity: 1; }
  85%, 87% { opacity: 0.32; }
  88%, 90% { opacity: 0.85; }
}

/* ──── F6 · STAMPEDE — arrows radiating ──── */
.fc-overlay-stampede .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,140,40,0.62),
    0 0 0 2px rgba(60,20,0,0.85),
    0 0 14px 2px rgba(255,140,40,0.42);
}
.fc-overlay-stampede:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,180,80,0.85),
    0 0 0 2.5px rgba(60,20,0,1),
    0 0 22px 4px rgba(255,140,40,0.78);
}
.fc-overlay-stampede .fc-encircle-avatar-img { filter: saturate(0.78); }
.fc-sd-a-1, .fc-sd-a-2, .fc-sd-a-3, .fc-sd-a-4,
.fc-sd-a-5, .fc-sd-a-6, .fc-sd-a-7, .fc-sd-a-8 { animation: fc-sd-shoot 11s ease-out infinite; }
.fc-sd-a-2 { animation-delay: 0.05s; }
.fc-sd-a-3 { animation-delay: 0.1s; }
.fc-sd-a-4 { animation-delay: 0.15s; }
.fc-sd-a-5 { animation-delay: 0.2s; }
.fc-sd-a-6 { animation-delay: 0.25s; }
.fc-sd-a-7 { animation-delay: 0.3s; }
.fc-sd-a-8 { animation-delay: 0.35s; }
.fc-sd-exit { animation: fc-sd-exit 11s ease-in-out infinite; }
@keyframes fc-sd-shoot {
  0%, 70%, 100% { opacity: 0; transform: scale(0.5); }
  72% { opacity: 1; transform: scale(1.15); }
  84% { opacity: 0.75; transform: scale(1); }
  90% { opacity: 0; transform: scale(1.1); }
}
@keyframes fc-sd-exit {
  0%, 70%, 100% { fill: rgba(255,80,40,0); transform: scale(1); }
  74%, 80% { fill: rgba(255,80,40,0.92); transform: scale(1.15); }
  85% { fill: rgba(255,80,40,0); transform: scale(1); }
}

/* ──── F7 · KARMA-DEBT — 7-segment counter ticking up ──── */
.fc-overlay-karma-debt .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(255,40,40,0.62),
    0 0 0 2px rgba(60,8,8,0.85),
    0 0 14px 2px rgba(255,40,40,0.42);
}
.fc-overlay-karma-debt:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(255,80,80,0.85),
    0 0 0 2.5px rgba(60,8,8,1),
    0 0 22px 4px rgba(255,40,40,0.78);
}
.fc-overlay-karma-debt .fc-encircle-avatar-img { filter: contrast(1.08) saturate(0.85); }
.fc-kd-count { animation: fc-kd-tick 7s steps(1) infinite; }
.fc-kd-flash { animation: fc-kd-flash 7s steps(1) infinite; }
@keyframes fc-kd-tick {
  0%, 14% { content: "0042"; }
  14%, 28% { content: "0043"; }
  28%, 42% { content: "0044"; }
  42%, 56% { content: "0045"; }
  56%, 70% { content: "0046"; }
  70%, 84% { content: "0047"; }
  84%, 100% { content: "0048"; }
}
@keyframes fc-kd-flash {
  0%, 6%, 14%, 20%, 28%, 34%, 42%, 48%, 56%, 62%, 70%, 76%, 84%, 90%, 100% { fill: rgba(255,40,40,0); }
  3%, 17%, 31%, 45%, 59%, 73%, 87% { fill: rgba(255,40,40,0.42); }
}

/* ──── F8 · FREEZE — Sanctions hold, ice spread ──── */
.fc-overlay-freeze .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 1.4px rgba(180,240,255,0.62),
    0 0 0 2px rgba(80,180,255,0.55),
    0 0 14px 2px rgba(180,240,255,0.42);
}
.fc-overlay-freeze:hover .fc-encircle-frame {
  box-shadow:
    inset 0 0 0 2px rgba(220,245,255,0.95),
    0 0 0 2.5px rgba(80,180,255,0.85),
    0 0 22px 4px rgba(180,240,255,0.78);
}
.fc-overlay-freeze .fc-encircle-avatar-img { filter: saturate(0.62) hue-rotate(-15deg) brightness(0.92); }
.fc-fz-h-1, .fc-fz-h-2, .fc-fz-h-3, .fc-fz-h-4, .fc-fz-h-5, .fc-fz-h-6 { animation: fc-fz-grow 25s ease-in-out infinite; }
.fc-fz-h-2 { animation-delay: 0.1s; }
.fc-fz-h-3 { animation-delay: 0.2s; }
.fc-fz-h-4 { animation-delay: 0.3s; }
.fc-fz-h-5 { animation-delay: 0.15s; }
.fc-fz-h-6 { animation-delay: 0.25s; }
.fc-fz-frost { animation: fc-fz-frost 25s ease-in-out infinite; }
@keyframes fc-fz-grow {
  0%, 80%, 100% { opacity: 0; transform: scale(0.5); }
  84%, 92% { opacity: 0.85; transform: scale(1.2); }
  96% { opacity: 0.35; transform: scale(1); }
}
@keyframes fc-fz-frost {
  0%, 80%, 100% { fill: rgba(140,200,255,0); }
  86%, 92% { fill: rgba(140,200,255,0.32); }
}

/* xs/sm overlay hides */
.fc-encircle-size-xs .fc-rd,
.fc-encircle-size-xs .fc-mf,
.fc-encircle-size-xs .fc-rg,
.fc-encircle-size-xs .fc-sh,
.fc-encircle-size-xs .fc-bn,
.fc-encircle-size-xs .fc-sd,
.fc-encircle-size-xs .fc-kd,
.fc-encircle-size-xs .fc-fz { display: none; }

/* ════════════════════════════════════════════════════════════════════
   Reduced motion — kill all animations universally
   ════════════════════════════════════════════════════════════════════ */
@media (prefers-reduced-motion: reduce) {
  .fc-encircle-shadow_chancellor::before,
  .fc-encircle-shadow_chancellor::after,
  .fc-encircle-shadow_chancellor .fc-encircle-frame,
  .fc-sauron-flame,
  .fc-sauron-flame-core,
  .fc-sauron-eyelid,
  .fc-sauron-ember,
  .fc-blackhole-singularity,
  .fc-skull-socket-left,
  .fc-skull-socket-right,
  /* §19: matrix streams + new variant frame animations
     §20: extended to 8 streams + glitch flicker + scanline drift */
  .fc-matrix-stream-1,
  .fc-matrix-stream-2,
  .fc-matrix-stream-3,
  .fc-matrix-stream-4,
  .fc-matrix-stream-5,
  .fc-matrix-stream-6,
  .fc-matrix-stream-7,
  .fc-matrix-stream-8,
  .fc-matrix-glyph-head,
  .fc-matrix-scanlines,
  /* §29 v1: panic-a/b/c overlay families */
  .fc-overlay-panic-a .fc-encircle-avatar-fallback,
  .fc-overlay-panic-a .fc-encircle-avatar-img,
  .fc-pa-scanlines, .fc-pa-noise, .fc-pa-scanbar,
  .fc-pa-ghost-r, .fc-pa-ghost-c, .fc-pa-sync-warn,
  .fc-pa-flash, .fc-pa-tear, .fc-pa-loss-band,
  .fc-pa-g-1, .fc-pa-g-2, .fc-pa-g-3, .fc-pa-g-4, .fc-pa-g-5, .fc-pa-g-6,
  .fc-overlay-panic-b .fc-encircle-avatar-fallback,
  .fc-overlay-panic-b .fc-encircle-avatar-img,
  .fc-pb-bit-1, .fc-pb-bit-2, .fc-pb-bit-3, .fc-pb-bit-4,
  .fc-pb-bit-5, .fc-pb-bit-6, .fc-pb-bit-7, .fc-pb-bit-8,
  .fc-pb-hex-group,
  .fc-pb-stack-1, .fc-pb-stack-2, .fc-pb-stack-3, .fc-pb-stack-4,
  .fc-pb-bsod,
  .fc-pb-crash-1, .fc-pb-crash-2, .fc-pb-crash-3, .fc-pb-crash-4,
  .fc-pb-crash-5, .fc-pb-crash-6, .fc-pb-crash-7, .fc-pb-crash-8,
  .fc-pb-crash-9, .fc-pb-crash-10, .fc-pb-crash-11, .fc-pb-crash-12,
  .fc-pb-title,
  .fc-overlay-panic-c .fc-encircle-avatar-fallback,
  .fc-overlay-panic-c .fc-encircle-avatar-img,
  .fc-pb-perma-stripe,
  .fc-overlay-panic-a .fc-encircle-frame,
  .fc-pc-fr-1, .fc-pc-fr-2, .fc-pc-fr-3,
  .fc-pc-crack-1, .fc-pc-crack-2, .fc-pc-crack-3, .fc-pc-crack-4, .fc-pc-crack-5,
  .fc-pc-p-1, .fc-pc-p-2, .fc-pc-p-3, .fc-pc-p-4, .fc-pc-p-5,
  .fc-pc-p-6, .fc-pc-p-7, .fc-pc-p-8, .fc-pc-p-9, .fc-pc-p-10,
  .fc-pc-p-11, .fc-pc-p-12, .fc-pc-p-13, .fc-pc-p-14, .fc-pc-p-15,
  .fc-pc-shard-1, .fc-pc-shard-2, .fc-pc-shard-3, .fc-pc-shard-4,
  .fc-pc-shard-5, .fc-pc-shard-6, .fc-pc-shard-7, .fc-pc-shard-8,
  .fc-pc-sigil {
    animation: none !important;
  }

  /* §pass39: sovereign variants — frame + all per-element animations */
  .fc-encircle-sovereign .fc-encircle-frame,
  .fc-aegis-dodec, .fc-aegis-pulse, .fc-aegis-heart, .fc-aegis-eq,
  .fc-prism-spectrum-wrap, .fc-prism-beacon-1, .fc-prism-beacon-2, .fc-prism-beacon-3,
  .fc-pano-eye-1, .fc-pano-eye-2, .fc-pano-eye-3, .fc-pano-eye-4, .fc-pano-eye-5, .fc-pano-eye-6,
  .fc-pano-singularity, .fc-pano-trace,
  .fc-vellum-seal, .fc-vellum-knife, .fc-vellum-crack,
  .fc-disp-column, .fc-disp-masthead, .fc-disp-breaking,
  .fc-bull-ribbon, .fc-bull-top, .fc-bull-sparkle,
  .fc-seal-ticks, .fc-seal-hash-1, .fc-seal-hash-2, .fc-seal-check,
  .fc-ozy-pillar, .fc-ozy-sand, .fc-ozy-crown,
  .fc-cl-horn, .fc-cl-scroll-l, .fc-cl-scroll-r, .fc-cl-coin-1, .fc-cl-coin-2, .fc-cl-coin-3,
  .fc-forge-molten, .fc-forge-haze, .fc-forge-star-1, .fc-forge-star-2, .fc-forge-star-3, .fc-forge-score,
  .fc-wv-spindle, .fc-weave .fc-wv-threads path, .fc-wv-claim,
  /* §pass39b — signature events */
  .fc-aegis-delta-breach, .fc-aegis-delta-ok, .fc-aegis-breach-flash,
  .fc-prism-stutter-r, .fc-prism-stutter-c,
  .fc-pano-target, .fc-pano-lock-text,
  .fc-vellum-redact,
  .fc-disp-extra,
  .fc-bull-dip,
  .fc-seal-revoked,
  .fc-ozy-erosion,
  .fc-cl-paid,
  .fc-forge-spill,
  .fc-wv-snip,
  /* §pass42b — Hagrid's bedrock variant animations */
  .fc-bk-cursor, .fc-bk-halo, .fc-bk-prompt, .fc-bk-warn-tick,
  .fc-bk-strata, .fc-bk-word,
  .fc-encircle-bedrock .fc-encircle-frame,
  /* §pass43 — 8 new broken-machine overlay animations */
  .fc-br-traces, .fc-br-arc-1, .fc-br-arc-2, .fc-br-arc-3,
  .fc-br-spark-1, .fc-br-spark-2, .fc-br-spark-3, .fc-br-flash,
  .fc-rf-ghost-c, .fc-rf-ghost-r, .fc-rf-prism, .fc-rf-prism-r, .fc-rf-prism-g, .fc-rf-prism-b,
  .fc-rf-ripple-1, .fc-rf-ripple-2, .fc-rf-ripple-3,
  .fc-rf-splash-r, .fc-rf-splash-g, .fc-rf-splash-b,
  .fc-st-buf-1, .fc-st-buf-2, .fc-st-buf-3, .fc-st-cursor,
  .fc-st-word-1, .fc-st-word-2, .fc-st-word-3,
  .fc-bl-seed-1, .fc-bl-seed-2, .fc-bl-drip-1, .fc-bl-drip-2,
  .fc-bl-pool, .fc-bl-halo, .fc-bl-glyph,
  .fc-ck-cracks-flare, .fc-ck-grow-1, .fc-ck-grow-2,
  .fc-ck-spark-1, .fc-ck-spark-2, .fc-ck-spark-3, .fc-ck-spark-4,
  .fc-fb-ring-1, .fc-fb-ring-2, .fc-fb-ring-3, .fc-fb-center,
  .fc-fb-overshoot-1, .fc-fb-overshoot-2, .fc-fb-screech,
  .fc-sp-ember-1, .fc-sp-ember-2, .fc-sp-ember-3, .fc-sp-ember-4, .fc-sp-ember-5,
  .fc-sp-droplet-1, .fc-sp-droplet-2, .fc-sp-droplet-3, .fc-sp-haze,
  .fc-un-nubs, .fc-un-thread-1, .fc-un-thread-2, .fc-un-tension, .fc-un-snap,
  .fc-overlay-breach .fc-encircle-frame,
  .fc-overlay-refract .fc-encircle-frame,
  .fc-overlay-stutter .fc-encircle-frame,
  .fc-overlay-bleed .fc-encircle-frame,
  .fc-overlay-crackle .fc-encircle-frame,
  .fc-overlay-feedback .fc-encircle-frame,
  .fc-overlay-spatter .fc-encircle-frame,
  .fc-overlay-unravel .fc-encircle-frame,
  /* §pass67 — registry full-cover variants + overlays */
  .fc-encircle-chancellery .fc-encircle-frame,
  .fc-chc-rotor, .fc-chc-pulse, .fc-chc-eagle,
  .fc-encircle-statehouse .fc-encircle-frame,
  .fc-sth-dome, .fc-sth-stars,
  .fc-encircle-bastille .fc-encircle-frame,
  .fc-bst-torch-1, .fc-bst-torch-2, .fc-bst-torch-3, .fc-bst-torch-4, .fc-bst-banner,
  .fc-encircle-ministry .fc-encircle-frame,
  .fc-min-ribbon, .fc-min-ink,
  .fc-encircle-olive-branch .fc-encircle-frame,
  .fc-olv-leaves-l, .fc-olv-leaves-r, .fc-olv-dove,
  .fc-encircle-cross-shield .fc-encircle-frame,
  .fc-csh-cross,
  .fc-encircle-lighthouse .fc-encircle-frame,
  .fc-lhs-beam-rotor, .fc-lhs-beacons circle,
  .fc-encircle-commons .fc-encircle-frame,
  .fc-cmn-rings, .fc-cmn-arrows,
  .fc-encircle-moonshot .fc-encircle-frame,
  .fc-mns-rocket, .fc-mns-trails, .fc-mns-stars circle, .fc-mns-text,
  .fc-encircle-diamond-hands .fc-encircle-frame,
  .fc-dmh-shards, .fc-dmh-shard-1, .fc-dmh-shard-2, .fc-dmh-shard-3,
  .fc-dmh-shard-4, .fc-dmh-shard-5, .fc-dmh-shard-6, .fc-dmh-fists,
  .fc-encircle-chad-frog .fc-encircle-frame,
  .fc-cfg-eye-l, .fc-cfg-eye-r, .fc-cfg-monocle, .fc-cfg-hand,
  .fc-encircle-pixel-shrine .fc-encircle-frame,
  .fc-pxs-coin, .fc-pxs-flame-1, .fc-pxs-flame-2, .fc-pxs-sparkles,
  .fc-encircle-savanna .fc-encircle-frame,
  .fc-svn-bird-1, .fc-svn-bird-2, .fc-svn-bird-3,
  .fc-encircle-andes .fc-encircle-frame,
  .fc-and-condor, .fc-and-band-top, .fc-and-band-bot,
  .fc-encircle-liberty .fc-encircle-frame,
  .fc-lib-flame, .fc-lib-crown,
  .fc-encircle-outback .fc-encircle-frame,
  .fc-otb-dots circle, .fc-otb-leaf,
  .fc-encircle-alpine .fc-encircle-frame,
  .fc-alp-snow-1, .fc-alp-snow-2, .fc-alp-snow-3, .fc-alp-snow-4, .fc-alp-snow-5, .fc-alp-edelweiss,
  .fc-encircle-bullion-vault .fc-encircle-frame,
  .fc-bvt-wheel, .fc-bvt-bolts polygon, .fc-bvt-ingot-1, .fc-bvt-ingot-2, .fc-bvt-ingot-3,
  /* §pass67 overlays */
  .fc-overlay-redaction .fc-encircle-frame,
  .fc-rd-bar-1, .fc-rd-bar-2, .fc-rd-bar-3, .fc-rd-bar-4, .fc-rd-stamp,
  .fc-overlay-manifold .fc-encircle-frame,
  .fc-mf-temp, .fc-mf-jet-n ellipse, .fc-mf-jet-e ellipse, .fc-mf-jet-sw ellipse, .fc-mf-bar,
  .fc-overlay-rugpull .fc-encircle-frame,
  .fc-rg-thread-1, .fc-rg-thread-2, .fc-rg-thread-3, .fc-rg-thread-4,
  .fc-rg-thread-5, .fc-rg-thread-6, .fc-rg-thread-7, .fc-rg-thread-8, .fc-rg-gg,
  .fc-overlay-shilling .fc-encircle-frame,
  .fc-sh-b-1, .fc-sh-b-2, .fc-sh-b-3, .fc-sh-b-4, .fc-sh-b-5,
  .fc-overlay-brownout .fc-encircle-frame,
  .fc-overlay-brownout .fc-encircle-avatar-img, .fc-bn-flicker,
  .fc-overlay-stampede .fc-encircle-frame,
  .fc-sd-a-1, .fc-sd-a-2, .fc-sd-a-3, .fc-sd-a-4,
  .fc-sd-a-5, .fc-sd-a-6, .fc-sd-a-7, .fc-sd-a-8, .fc-sd-exit,
  .fc-overlay-karma-debt .fc-encircle-frame, .fc-kd-count, .fc-kd-flash,
  .fc-overlay-freeze .fc-encircle-frame,
  .fc-fz-h-1, .fc-fz-h-2, .fc-fz-h-3, .fc-fz-h-4, .fc-fz-h-5, .fc-fz-h-6, .fc-fz-frost {
    animation: none !important;
  }

  /* §26 v1: cascade frame + all overlay element animations */
  .fc-overlay-cascade .fc-encircle-frame,
  .fc-overlay-cascade .fc-encircle-avatar-fallback,
  .fc-overlay-cascade .fc-encircle-avatar-img,
  .fc-cascade-scanlines,
  .fc-cascade-halu-1, .fc-cascade-halu-2, .fc-cascade-halu-3, .fc-cascade-halu-4,
  .fc-cascade-halu-5, .fc-cascade-halu-6, .fc-cascade-halu-7, .fc-cascade-halu-8,
  .fc-cascade-vtear-1, .fc-cascade-vtear-2, .fc-cascade-vtear-3, .fc-cascade-vtear-4,
  .fc-cascade-pxl-1, .fc-cascade-pxl-2, .fc-cascade-pxl-3, .fc-cascade-pxl-4, .fc-cascade-pxl-5,
  .fc-cascade-blackout,
  .fc-cascade-col-1, .fc-cascade-col-2, .fc-cascade-col-3, .fc-cascade-col-4 {
    animation: none !important;
  }

  /* §21 v3: glitch frame + all overlay element animations */
  .fc-overlay-glitch .fc-encircle-frame,
  .fc-overlay-glitch .fc-encircle-avatar-fallback,
  .fc-overlay-glitch .fc-encircle-avatar-img,
  .fc-glitch-scanlines-v3,
  .fc-glitch-crt-beam-v3,
  .fc-glitch-tear-1,
  .fc-glitch-tear-2,
  .fc-glitch-tear-3,
  .fc-glitch-tear-4,
  .fc-glitch-tear-5,
  .fc-glitch-tear-6,
  .fc-glitch-tear-7,
  .fc-glitch-diamond-1,
  .fc-glitch-diamond-2,
  .fc-glitch-diamond-3,
  .fc-glitch-flash-v3,
  .fc-glitch-strip-major-1,
  .fc-glitch-strip-major-2,
  .fc-glitch-noise-v3,
  .fc-glitch-glyph-1,
  .fc-glitch-glyph-2,
  .fc-glitch-glyph-3 {
    animation: none !important;
  }
  /* §20 seasonal animations also disabled with reduced-motion */
  .fc-encircle-shadow_chancellor.fc-encircle-yule .fc-encircle-frame,
  .fc-encircle-shadow_chancellor.fc-encircle-solstice .fc-encircle-frame {
    animation: none !important;
  }
  /* Hide embers entirely with reduced-motion (they only make sense
     animated; static embers in mid-flight look weird). */
  .fc-sauron-ember { opacity: 0 !important; }
  /* Hide matrix streams + glitch + cascade + panic overlays entirely with reduced-motion. */
  .fc-matrix-rain { opacity: 0 !important; }
  .fc-glitch-v3 { opacity: 0 !important; }
  .fc-cascade-v1 { opacity: 0 !important; }
  .fc-panic-v1 { opacity: 0 !important; }
}
</style>
