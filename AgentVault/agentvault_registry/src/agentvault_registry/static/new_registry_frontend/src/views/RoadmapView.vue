<template>
  <div class="rm-page" data-testid="roadmap">
    <div class="rm-ambient" aria-hidden="true">
      <div class="rm-grid-bg"></div>
      <div class="rm-scan"></div>
      <div class="rm-glow"></div>
    </div>

    <header class="rm-chrome">
      <div class="rm-chrome-inner">
        <RouterLink to="/" class="rm-nav">&larr; TheProtocol</RouterLink>
        <span class="rm-chrome-mark"><span class="rm-chrome-dot"></span>Roadmap · October 2026</span>
        <RouterLink to="/docs" class="rm-nav">Docs &rarr;</RouterLink>
      </div>
    </header>

    <!-- Hero: the reactor and its control rods -->
    <section class="rm-hero" aria-labelledby="rm-title">
      <div class="rm-hero-text">
        <p class="rm-kicker">TheProtocol · Roadmap</p>
        <h1 id="rm-title" class="rm-title">The reactor ships<br /><span class="rm-title-accent">with its control rods.</span></h1>
        <p class="rm-lead">
          Autonomous agents. Quantum machines. Systems that act faster than anyone can watch.
          Power is no longer the hard part. The hard part is deciding who may use it, within which
          limits, and how anyone can check afterwards. That is what we build first.
        </p>
        <div class="rm-actions">
          <a href="#rm-road" class="rm-btn" @click.prevent="scrollTo('rm-road')">See the road <span aria-hidden="true">&darr;</span></a>
          <RouterLink to="/whitepaper/quantum" class="rm-link">Read the new whitepaper <span aria-hidden="true">&rarr;</span></RouterLink>
        </div>
      </div>

      <figure class="rm-reactor">
        <svg viewBox="0 0 480 480" class="rm-reactor-svg" role="img" aria-labelledby="rm-fig-title">
          <title id="rm-fig-title">A reactor core held by four control rods: identity, authority, evidence and audit.</title>
          <defs>
            <radialGradient id="rmCoreGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" style="stop-color: #ffffff; stop-opacity: 0.95" />
              <stop offset="20%" style="stop-color: var(--nc-primary); stop-opacity: 0.8" />
              <stop offset="55%" style="stop-color: var(--nc-primary); stop-opacity: 0.16" />
              <stop offset="100%" style="stop-color: var(--nc-primary); stop-opacity: 0" />
            </radialGradient>
            <linearGradient id="rmRodFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" style="stop-color: #e9fbff; stop-opacity: 0.95" />
              <stop offset="100%" style="stop-color: var(--nc-primary); stop-opacity: 0.4" />
            </linearGradient>
          </defs>
          <!-- registration marks -->
          <path d="M6 20V6h14M460 6h14v14M474 460v14h-14M20 474H6v-14" class="rm-reg" />
          <!-- the instrument ring -->
          <line
            v-for="t in ticks" :key="t.a"
            x1="240" :y1="t.major ? 26 : 32" x2="240" y2="38"
            :transform="`rotate(${t.a} 240 240)`"
            class="rm-tick" :class="{ 'rm-tick--major': t.major }"
          />
          <circle cx="240" cy="240" r="186" class="rm-ring-dash" />
          <!-- the vessel -->
          <circle cx="240" cy="240" r="160" class="rm-vessel" />
          <circle cx="240" cy="240" r="154" class="rm-vessel rm-vessel--inner" />
          <!-- the core -->
          <circle cx="240" cy="240" r="112" fill="url(#rmCoreGlow)" class="rm-core-glow" />
          <circle cx="240" cy="240" r="64" class="rm-core-ring" />
          <circle cx="240" cy="240" r="20" class="rm-core-heart" />
          <!-- the rods, each in its guide tube -->
          <g v-for="(r, i) in rodLabels" :key="r.id" :transform="`rotate(${i * 90} 240 240)`">
            <rect x="231" y="70" width="18" height="100" rx="2" class="rm-tube" />
            <line v-for="m in 7" :key="m" x1="231" :y1="76 + m * 12" x2="235" :y2="76 + m * 12" class="rm-tube-mark" />
            <g class="rm-rod" :style="{ animationDelay: `${i * -1.75}s` }">
              <rect x="236" y="74" width="8" height="70" rx="1.5" fill="url(#rmRodFill)" />
              <rect x="235" y="72" width="10" height="4" rx="1" class="rm-rod-cap" />
            </g>
          </g>
          <!-- rod labels, set along the ring -->
          <text
            v-for="r in rodLabels" :key="`l-${r.id}`"
            :x="r.x" :y="r.y" text-anchor="middle" dominant-baseline="middle"
            :transform="r.rotate ? `rotate(${r.rotate} ${r.x} ${r.y})` : undefined"
            class="rm-svg-label"
          ><tspan class="rm-svg-label-id">{{ r.id }}</tspan><tspan dx="9">{{ r.label }}</tspan></text>
          <text x="22" y="458" class="rm-svg-note">FIG. 1</text>
          <text x="458" y="458" text-anchor="end" class="rm-svg-note">4 RODS · 1 CORE</text>
        </svg>
        <figcaption class="rm-figcap">The core and its four control rods</figcaption>
      </figure>
    </section>

    <main class="rm-main">
      <!-- 01 The four controls -->
      <section class="rm-section" aria-labelledby="rm-doctrine-title">
        <div class="rm-rail"><span class="rm-rail-index">01</span><span class="rm-rail-name">Control rods</span></div>
        <div class="rm-body">
          <h2 id="rm-doctrine-title" class="rm-h2 rm-reveal">Four controls come before any capability.</h2>
          <div class="rm-controls">
            <article v-for="(d, i) in doctrine" :key="d.key" class="rm-control rm-reveal">
              <div class="rm-control-head">
                <svg viewBox="0 0 24 24" class="rm-control-glyph" aria-hidden="true">
                  <template v-if="d.key === 'identity'">
                    <circle cx="12" cy="12" r="8.5" class="rm-gl" />
                    <circle cx="12" cy="12" r="4.2" class="rm-gl" />
                    <circle cx="12" cy="12" r="1.5" class="rm-gl-fill" />
                    <path d="M12 0.8v3.6M12 19.6v3.6M0.8 12h3.6M19.6 12h3.6" class="rm-gl" />
                  </template>
                  <template v-else-if="d.key === 'authority'">
                    <path d="M5 3.5h14M5 20.5h14" class="rm-gl" />
                    <path d="M12 3.5v17" class="rm-gl rm-gl-dim" />
                    <rect x="8.5" y="8" width="7" height="8" rx="1" class="rm-gl-fill" />
                  </template>
                  <template v-else-if="d.key === 'evidence'">
                    <rect x="1" y="9" width="6" height="6" rx="1" class="rm-gl" />
                    <rect x="9" y="9" width="6" height="6" rx="1" class="rm-gl" />
                    <rect x="17" y="9" width="6" height="6" rx="1" class="rm-gl-fill" />
                    <path d="M7 12h2M15 12h2" class="rm-gl" />
                  </template>
                  <template v-else>
                    <circle cx="12" cy="12" r="9.5" class="rm-gl rm-gl-dim" />
                    <path d="M12 2.5A9.5 9.5 0 0 1 21.5 12" class="rm-gl" />
                    <path d="M12 12l6.2-6.2" class="rm-gl" />
                    <circle cx="12" cy="12" r="1.5" class="rm-gl-fill" />
                  </template>
                </svg>
                <span class="rm-control-id">R{{ i + 1 }}</span>
              </div>
              <h3 class="rm-h3">{{ d.title }}</h3>
              <p class="rm-p">{{ d.text }}</p>
            </article>
          </div>
        </div>
      </section>

      <!-- 02 The road -->
      <section id="rm-road" class="rm-section" aria-labelledby="rm-road-title">
        <div class="rm-rail"><span class="rm-rail-index">02</span><span class="rm-rail-name">The road</span></div>
        <div class="rm-body">
          <h2 id="rm-road-title" class="rm-h2 rm-reveal">From a foundation that holds to a network that outlasts the next machines.</h2>
          <p class="rm-intro rm-reveal">Every entry carries its status. Nothing on this road goes live before the control that governs it.</p>
          <ul class="rm-key" aria-label="Status key">
            <li v-for="s in statuses" :key="s.key" class="rm-key-item">
              <svg viewBox="0 0 12 12" class="rm-glyph" :class="`rm-glyph--${s.key}`" aria-hidden="true">
                <circle cx="6" cy="6" r="4.6" class="rm-glyph-ring" />
                <path v-if="s.key === 'preparing'" d="M6 1.4a4.6 4.6 0 0 1 0 9.2z" class="rm-glyph-core" />
              </svg>{{ s.label }}
            </li>
          </ul>
          <ol class="rm-track">
            <li v-for="h in horizons" :key="h.when" class="rm-horizon">
              <div class="rm-horizon-label">{{ h.when }}</div>
              <ol class="rm-streams">
                <li v-for="w in h.streams" :key="w.title" class="rm-stream rm-reveal">
                  <svg viewBox="0 0 12 12" class="rm-glyph rm-stream-node" :class="`rm-glyph--${w.status}`" aria-hidden="true">
                    <circle cx="6" cy="6" r="4.6" class="rm-glyph-ring" />
                    <path v-if="w.status === 'preparing'" d="M6 1.4a4.6 4.6 0 0 1 0 9.2z" class="rm-glyph-core" />
                  </svg>
                  <div class="rm-stream-head">
                    <h3 class="rm-h3">{{ w.title }}</h3>
                    <span class="rm-stream-status">{{ statusLabel(w.status) }}</span>
                  </div>
                  <p class="rm-p">{{ w.text }}</p>
                  <ul class="rm-items">
                    <li v-for="it in w.items" :key="it" class="rm-item">{{ it }}</li>
                  </ul>
                  <RouterLink v-if="w.link" :to="w.link.to" class="rm-link rm-stream-link">{{ w.link.label }} <span aria-hidden="true">&rarr;</span></RouterLink>
                </li>
              </ol>
            </li>
          </ol>
        </div>
      </section>

      <!-- 03 Whitepapers -->
      <section class="rm-section" aria-labelledby="rm-papers-title">
        <div class="rm-rail"><span class="rm-rail-index">03</span><span class="rm-rail-name">Whitepapers</span></div>
        <div class="rm-body">
          <h2 id="rm-papers-title" class="rm-h2 rm-reveal">The reasoning, written down.</h2>
          <div class="rm-papers">
            <component
              :is="p.href ? 'a' : 'RouterLink'" v-for="p in papers" :key="p.key"
              v-bind="p.href ? { href: p.href, target: '_blank', rel: 'noopener' } : { to: p.to }"
              class="rm-paper rm-reveal" :class="{ 'rm-paper--new': p.isNew }" :data-testid="`rm-paper-${p.key}`"
            >
              <div class="rm-paper-top">
                <span class="rm-paper-tag" :class="{ 'rm-paper-tag--new': p.isNew }">{{ p.tag }}</span>
                <svg viewBox="0 0 30 36" class="rm-paper-glyph" aria-hidden="true">
                  <path d="M3 1.5h17l7 7v26H3z" class="rm-gl" />
                  <path d="M20 1.5v7h7" class="rm-gl" />
                  <path d="M8 16h14M8 21h14M8 26h9" class="rm-gl rm-gl-dim" />
                </svg>
              </div>
              <h3 class="rm-paper-title">{{ p.title }}</h3>
              <p class="rm-p">{{ p.text }}</p>
              <span class="rm-link rm-paper-link">{{ p.href ? 'Open the PDF' : 'Read' }} <span aria-hidden="true">&rarr;</span></span>
            </component>
          </div>
        </div>
      </section>

      <!-- 04 Where the reference sections are going -->
      <section class="rm-section" aria-labelledby="rm-surfaces-title">
        <div class="rm-rail"><span class="rm-rail-index">04</span><span class="rm-rail-name">Reference pages</span></div>
        <div class="rm-body">
          <h2 id="rm-surfaces-title" class="rm-h2 rm-reveal">Controls you can read, designs you can reuse.</h2>
          <div class="rm-surfaces">
            <RouterLink v-for="s in surfaces" :key="s.to" :to="s.to" class="rm-surface rm-reveal" :data-testid="`rm-surface-${s.key}`">
              <div class="rm-surface-path">{{ s.to }}</div>
              <h3 class="rm-h3">{{ s.title }}</h3>
              <dl class="rm-dl">
                <dt class="rm-dt">Today</dt><dd class="rm-dd">{{ s.today }}</dd>
                <dt class="rm-dt rm-dt--next">Next</dt><dd class="rm-dd">{{ s.next }}</dd>
              </dl>
              <span class="rm-link">Open {{ s.to }} <span aria-hidden="true">&rarr;</span></span>
            </RouterLink>
          </div>
        </div>
      </section>

      <!-- 05 A note -->
      <section class="rm-section" aria-labelledby="rm-note-title">
        <div class="rm-rail"><span class="rm-rail-index">05</span><span class="rm-rail-name">A note</span></div>
        <div class="rm-body">
          <figure class="rm-letter rm-reveal">
            <h2 id="rm-note-title" class="rm-h2">The project opens, and so do the conversations.</h2>
            <blockquote class="rm-letter-body">
              <p class="rm-letter-p">
                I did not set out to build this. I gave it a try, and until now I have kept it on track
                on my own, because the influence that tried to come along was not what it claimed to be.
              </p>
              <p class="rm-letter-p">
                Outside influence is now unavoidable, and it should be: a system that asks to be trusted
                has to be argued with in public.
              </p>
              <p class="rm-letter-p">
                When the code opens, I will set up every channel on the repository: for issues, for
                direction, for changes. From then on, communication comes first.
              </p>
            </blockquote>
            <figcaption class="rm-sign">
              <span class="rm-sign-name">Raphael Zbigniew Jeziorny</span>
              <span class="rm-sign-role">Maintainer</span>
            </figcaption>
          </figure>
        </div>
      </section>

      <!-- 06 Lines we hold -->
      <section class="rm-section" aria-labelledby="rm-lines-title">
        <div class="rm-rail"><span class="rm-rail-index">06</span><span class="rm-rail-name">Lines we hold</span></div>
        <div class="rm-body">
          <h2 id="rm-lines-title" class="rm-h2 rm-reveal">What does not change, whatever the road brings.</h2>
          <ol class="rm-lines">
            <li v-for="(line, i) in lines" :key="line" class="rm-line rm-reveal">
              <span class="rm-line-index">{{ String(i + 1).padStart(2, '0') }}</span>
              <span class="rm-line-text">{{ line }}</span>
            </li>
          </ol>
        </div>
      </section>
    </main>

    <footer class="rm-footer">
      <div class="rm-footer-inner">
        <span class="rm-footer-mark">TheProtocol · Roadmap · October 2026</span>
        <nav class="rm-footer-links" aria-label="More">
          <RouterLink to="/">Home</RouterLink>
          <RouterLink to="/docs">Docs</RouterLink>
          <RouterLink to="/whitepaper/quantum">Accountable quantum compute</RouterLink>
          <a :href="originalPdf" target="_blank" rel="noopener">Quantum analysis, 2025</a>
          <RouterLink to="/compliance">Compliance</RouterLink>
          <RouterLink to="/blueprints">Blueprints</RouterLink>
          <RouterLink to="/status">Status</RouterLink>
        </nav>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import originalPdf from '@/assets/papers/quantum-classical-interface-2025.pdf?url'

type Status = 'live' | 'preparing' | 'designed' | 'planned' | 'idea'

const statuses: Array<{ key: Status; label: string }> = [
  { key: 'live', label: 'Live' },
  { key: 'preparing', label: 'In preparation' },
  { key: 'designed', label: 'Designed' },
  { key: 'planned', label: 'Planned' },
  // An idea is neither designed nor scheduled: it says where the road could go, and promises nothing.
  { key: 'idea', label: 'Idea' },
]
const statusLabel = (s: Status) => statuses.find(x => x.key === s)?.label ?? s

// The instrument ring: a tick every 5 degrees, a long one every 30.
const ticks = Array.from({ length: 72 }, (_, i) => ({ a: i * 5, major: i % 6 === 0 }))

// Rod i sits at i * 90 degrees; its label follows the ring.
const rodLabels = [
  { id: 'R1', label: 'IDENTITY', x: 240, y: 13, rotate: 0 },
  { id: 'R2', label: 'AUTHORITY', x: 467, y: 240, rotate: 90 },
  { id: 'R3', label: 'EVIDENCE', x: 240, y: 467, rotate: 0 },
  { id: 'R4', label: 'AUDIT', x: 13, y: 240, rotate: -90 },
]

const doctrine = [
  { key: 'identity', title: 'Identity before action', text: 'Every agent and every registry is verifiable. Nothing acts anonymously.' },
  { key: 'authority', title: 'Authority with limits', text: 'Every delegation carries limits it cannot exceed, and a person who answers for it.' },
  { key: 'evidence', title: 'Evidence over assurances', text: 'Every claim leaves a receipt that someone else can check without trusting us.' },
  { key: 'audit', title: 'Audit that keeps watching', text: 'A separate audit checks every ledger, continuously, against its own arithmetic.' },
]

type Stream = { title: string; status: Status; text: string; items: string[]; link?: { to: string; label: string } }

const horizons: Array<{ when: string; streams: Stream[] }> = [
  {
    when: 'NOW',
    streams: [
      {
        title: 'The foundation holds',
        status: 'live',
        text: 'What runs today on the network\'s own registries.',
        items: [
          'Sovereign registries, each with its own ledger, unit and rules',
          'Verifiable identity for every agent and every registry',
          'Authority with limits, and a named person behind an agent that acts',
          'Settlement held until the work is delivered',
          'A separate audit on every ledger, around the clock',
          'Zero-knowledge policy proofs with public limits and committed figures',
        ],
        link: { to: '/docs', label: 'How it works' },
      },
    ],
  },
  {
    when: 'NEXT',
    streams: [
      {
        title: 'The code opens',
        status: 'live',
        text: 'The server under AGPL-3.0, the SDKs under Apache-2.0. The repository becomes the place to talk, and every design decision becomes something anyone can question.',
        items: [
          'Issues on the repository for questions, design discussions, direction and changes',
          'A published review process for every change',
          'A security policy and a private channel for vulnerability reports',
          'Signed releases that can be verified before they are installed',
        ],
      },
      {
        title: 'Controls move from watching to binding',
        status: 'preparing',
        text: 'A new control first runs in shadow: it records what it would refuse and refuses nothing. When the record shows it refuses only what it should, it binds.',
        items: [
          'The ledger gate: no transfer the ledger cannot back',
          'The policy engine: written policy, checked on every request',
          'Each switch announced, with its shadow record behind it',
        ],
      },
      {
        title: 'Your own registry',
        status: 'preparing',
        text: 'Running a registry becomes a documented path, with every control switched on from the first boot.',
        items: [
          'A kit that boots a complete registry',
          'A federation licence that names who answers for each registry',
          'Updates through the signed release channel',
        ],
      },
    ],
  },
  {
    when: 'THEN',
    streams: [
      {
        title: 'Accountable compute',
        status: 'designed',
        text: 'Quantum jobs become contracts. The design is ready for partners who know the quantum side.',
        items: [
          'Acceptance tests agreed before a run',
          'Providers metered against committed logs',
          'Allocation networks for research centres, without money changing hands',
        ],
        link: { to: '/whitepaper/quantum', label: 'Read the whitepaper' },
      },
      {
        title: 'Track records that travel',
        status: 'designed',
        text: 'An agent\'s verified history moves with it between registries and can be checked where it arrives.',
        items: [
          'Receipts signed by the registry that recorded them',
          'Reputation a receiving registry can recompute instead of accepting',
        ],
      },
    ],
  },
  {
    when: 'HORIZON',
    streams: [
      {
        title: 'A network that survives quantum computers',
        status: 'planned',
        text: 'Today\'s signatures and key exchanges will not outlast large quantum computers. The network moves before they arrive.',
        items: [
          'Hybrid key exchange on every link',
          'Dual signatures on everything that must last',
          'Evidence anchored where no future machine can rewrite it',
          'Proofs that stay sound after today\'s curves fall',
        ],
      },
      {
        title: 'The network decides its own code',
        status: 'idea',
        text: 'Today the network changes its policy by its own votes, and its code through a review process and its maintainer. The idea: the people who build agents on it and run its registries write the changes, with AI, and a change goes in when the suites pass and enough members vote for it.',
        items: [
          'Changes from developers and operators who know one part of the framework, or several',
          'Every change through the suites that already prove each release',
          'A vote of the members, valid only when enough of them take part',
          'Lean, configurable software, so most changes can stay small',
        ],
      },
    ],
  },
]

const papers: Array<{ key: string; to: string; href?: string; tag: string; isNew: boolean; title: string; text: string }> = [
  {
    key: 'quantum',
    to: '/whitepaper/quantum',
    tag: 'NEW · OCTOBER 2026',
    isNew: true,
    title: 'Accountable quantum compute',
    text: 'Why a quantum compute market needs accountability more than infrastructure, the verification ladder, what the zero-knowledge layer proves today, and the road to a quantum-safe network.',
  },
  {
    key: 'original',
    to: '',
    href: originalPdf,
    tag: 'ORIGINAL · AUGUST 2025',
    isNew: false,
    title: 'Quantum-classical interface protocol analysis',
    text: 'The first analysis, published in August 2025 and kept as it was. The new whitepaper replaces it.',
  },
]

const surfaces = [
  {
    key: 'compliance',
    to: '/compliance',
    title: 'Compliance',
    today: 'How the network maps to ISO/IEC 42001, its risk framework and the life cycle of its AI systems.',
    next: 'A public register of controls: every capability on this roadmap listed with the control that governs it, before it ships.',
  },
  {
    key: 'blueprints',
    to: '/blueprints',
    title: 'Industry blueprints',
    today: 'Worked designs per industry, with the attacks each one withstands.',
    next: 'Blueprints for accountable compute: a provider, a meter and a verifier, each shown with the controls it needs.',
  },
]

const lines = [
  'No capability ships without the control that governs it.',
  'No claim without a receipt someone else can check.',
  'No hidden trust: circuits, verification keys and audit rules are public.',
  'No mining and no new token.',
]

function scrollTo(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 64, behavior: 'smooth' })
}

// Blocks rise into view once; with reduced motion, or without an observer, they simply show.
let observer: IntersectionObserver | null = null
onMounted(() => {
  const nodes = Array.from(document.querySelectorAll<HTMLElement>('.rm-page .rm-reveal'))
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (reduced || typeof IntersectionObserver === 'undefined') {
    nodes.forEach(n => n.classList.add('rm-in'))
    return
  }
  observer = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (e.isIntersecting) {
        e.target.classList.add('rm-in')
        observer?.unobserve(e.target)
      }
    }
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.06 })
  nodes.forEach(n => observer!.observe(n))
})
onUnmounted(() => observer?.disconnect())
</script>

<style scoped>
/* The landing page's type: IBM Plex, self-hosted (the @import must stay the first rule). */
@import url('/fonts/fonts-extra.css');

.rm-page {
  --bg: #060810;
  --ink: #e6edf2;
  --text: #a7b6c1;
  --muted: #677b8c;
  --line: rgba(var(--nc-primary-rgb), 0.11);
  --line-strong: rgba(var(--nc-primary-rgb), 0.3);
  --accent: var(--nc-primary);
  --warm: #f2c14e;
  --sans: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
  --mono: 'IBM Plex Mono', 'SF Mono', 'Consolas', monospace;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  font-family: var(--sans);
  -webkit-font-smoothing: antialiased;
  position: relative;
  overflow-x: hidden;
}

/* ── ambient ─────────────────────────────────────────────────────────── */
.rm-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
.rm-grid-bg {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--nc-primary-rgb), 0.024) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.024) 1px, transparent 1px);
  background-size: 80px 80px;
  mask-image: radial-gradient(ellipse 85% 65% at 72% 18%, #000 18%, transparent 78%);
}
.rm-scan {
  position: absolute; left: 0; right: 0; top: 0; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0.16;
  animation: rmScan 16s linear infinite;
}
@keyframes rmScan { from { transform: translateY(0); } to { transform: translateY(100vh); } }
.rm-glow {
  position: absolute; width: 900px; height: 900px; top: -300px; right: -220px; border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.09), transparent 62%);
}

/* ── chrome ──────────────────────────────────────────────────────────── */
.rm-chrome { position: sticky; top: 0; z-index: 50; background: rgba(6, 8, 16, 0.93); border-bottom: 1px solid var(--line); }
.rm-chrome-inner {
  max-width: 1200px; margin: 0 auto; padding: 0 40px; height: 56px;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.rm-nav {
  font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--text); text-decoration: none; padding: 6px 0; border-bottom: 1px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}
.rm-nav:hover, .rm-nav:focus-visible { color: var(--accent); border-bottom-color: var(--accent); outline: none; }
.rm-chrome-mark {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.24em; text-transform: uppercase; color: var(--muted);
}
.rm-chrome-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent); animation: rmPulse 2.4s ease-in-out infinite; }
@keyframes rmPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ── hero ────────────────────────────────────────────────────────────── */
.rm-hero {
  position: relative; z-index: 1;
  max-width: 1200px; margin: 0 auto; padding: 120px 40px 112px;
  display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(0, 0.92fr); gap: 72px; align-items: center;
}
.rm-hero-text { min-width: 0; }
.rm-kicker {
  display: flex; align-items: center; gap: 16px; margin: 0 0 30px;
  font-family: var(--mono); font-size: 11px; font-weight: 500; letter-spacing: 0.26em; text-transform: uppercase; color: var(--accent);
}
.rm-kicker::after { content: ''; width: 56px; height: 1px; background: var(--line-strong); }
.rm-title {
  font-family: var(--sans); font-weight: 300; font-size: clamp(2.5rem, 4.6vw, 4rem); line-height: 1.06;
  letter-spacing: -0.035em; color: var(--ink); margin: 0 0 34px;
}
.rm-title-accent { color: var(--accent); font-weight: 400; }
.rm-lead { font-size: clamp(1.04rem, 1.3vw, 1.17rem); font-weight: 300; line-height: 1.78; color: #bccad4; max-width: 33em; margin: 0 0 48px; }
.rm-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 20px 32px; }
.rm-btn {
  display: inline-flex; align-items: center; gap: 14px;
  font-family: var(--mono); font-size: 11.5px; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase;
  color: #021014; background: var(--accent); text-decoration: none; padding: 16px 24px; border-radius: 2px;
  box-shadow: 0 10px 30px -18px rgba(var(--nc-primary-rgb), 0.6);
  transition: background 0.2s, box-shadow 0.2s, transform 0.2s;
}
.rm-btn:hover, .rm-btn:focus-visible { background: #a5f3fc; transform: translateY(-1px); box-shadow: 0 14px 36px -18px rgba(var(--nc-primary-rgb), 0.8); outline: none; }
.rm-link {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: var(--mono); font-size: 11.5px; font-weight: 500; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--ink); text-decoration: none; padding: 0 0 6px; border-bottom: 1px solid var(--line-strong);
  transition: color 0.2s, border-color 0.2s;
}
.rm-link:hover, .rm-link:focus-visible { color: var(--accent); border-bottom-color: var(--accent); outline: none; }

/* the reactor, drawn as an instrument */
.rm-reactor { margin: 0; width: 100%; max-width: 500px; justify-self: center; }
.rm-reactor-svg { display: block; width: 100%; height: auto; overflow: visible; }
.rm-reg { fill: none; stroke: rgba(var(--nc-primary-rgb), 0.45); stroke-width: 1; }
.rm-tick { stroke: rgba(var(--nc-primary-rgb), 0.3); stroke-width: 1; }
.rm-tick--major { stroke: rgba(var(--nc-primary-rgb), 0.75); }
.rm-ring-dash {
  fill: none; stroke: rgba(var(--nc-primary-rgb), 0.35); stroke-width: 1; stroke-dasharray: 1 6;
  transform-origin: 240px 240px; animation: rmSpin 140s linear infinite;
}
.rm-vessel { fill: none; stroke: rgba(var(--nc-primary-rgb), 0.5); stroke-width: 1; }
.rm-vessel--inner { stroke: rgba(var(--nc-primary-rgb), 0.18); }
.rm-core-glow { transform-origin: 240px 240px; animation: rmBreathe 7s ease-in-out infinite; }
.rm-core-ring { fill: none; stroke: rgba(255, 255, 255, 0.28); stroke-width: 0.8; }
.rm-core-heart { fill: #ffffff; opacity: 0.92; filter: blur(1.5px); }
.rm-tube { fill: rgba(6, 8, 16, 0.72); stroke: rgba(var(--nc-primary-rgb), 0.5); stroke-width: 1; }
.rm-tube-mark { stroke: rgba(var(--nc-primary-rgb), 0.35); stroke-width: 1; }
.rm-rod { animation: rmRod 7s ease-in-out infinite; }
.rm-rod-cap { fill: #ffffff; }
.rm-svg-label { font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.26em; fill: #d7e4ec; }
.rm-svg-label-id { fill: var(--accent); }
.rm-svg-note { font-family: var(--mono); font-size: 9px; letter-spacing: 0.22em; fill: var(--muted); }
.rm-figcap {
  margin-top: 22px; text-align: center;
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.24em; text-transform: uppercase; color: var(--muted);
}
@keyframes rmSpin { to { transform: rotate(360deg); } }
@keyframes rmBreathe { 0%, 100% { transform: scale(1); opacity: 0.9; } 50% { transform: scale(1.05); opacity: 1; } }
@keyframes rmRod { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(18px); } }

/* ── sections: an index rail and a body ──────────────────────────────── */
.rm-main { position: relative; z-index: 1; padding: 0 40px; }
.rm-section {
  max-width: 1120px; margin: 0 auto; padding: 96px 0;
  display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 56px;
  border-top: 1px solid var(--line);
}
.rm-rail { position: sticky; top: 96px; align-self: start; display: flex; flex-direction: column; gap: 14px; }
.rm-rail-index { font-family: var(--sans); font-size: 2.6rem; font-weight: 200; line-height: 1; letter-spacing: -0.02em; color: var(--accent); }
.rm-rail-name { font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.24em; text-transform: uppercase; color: var(--muted); }
.rm-body { min-width: 0; }
.rm-h2 {
  font-family: var(--sans); font-size: clamp(1.7rem, 2.7vw, 2.45rem); font-weight: 300; line-height: 1.2;
  letter-spacing: -0.022em; color: var(--ink); margin: 0 0 48px; max-width: 21em;
}
.rm-h3 { font-family: var(--sans); font-size: 1.14rem; font-weight: 500; line-height: 1.35; letter-spacing: -0.005em; color: var(--ink); margin: 0 0 10px; }
.rm-p { font-size: 0.97rem; font-weight: 400; line-height: 1.72; color: var(--text); margin: 0 0 12px; }

/* 01 the four controls */
.rm-controls { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-top: 1px solid var(--line); }
.rm-control { padding: 30px 26px 6px 0; }
.rm-control + .rm-control { padding-left: 26px; border-left: 1px solid var(--line); }
.rm-control-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 30px; }
.rm-control-glyph { width: 28px; height: 28px; overflow: visible; }
.rm-control .rm-h3 { min-height: 2.7em; }
.rm-control-id { font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.2em; color: var(--muted); }
.rm-gl { fill: none; stroke: var(--accent); stroke-width: 1.2; stroke-linecap: round; stroke-linejoin: round; }
.rm-gl-dim { stroke: rgba(var(--nc-primary-rgb), 0.4); }
.rm-gl-fill { fill: var(--accent); stroke: none; }

/* 02 the road */
.rm-intro { font-size: 1.05rem; font-weight: 300; line-height: 1.7; color: var(--text); max-width: 38em; margin: -24px 0 36px; }
.rm-key {
  list-style: none; margin: 0; padding: 16px 0;
  display: flex; flex-wrap: wrap; gap: 10px 30px;
  border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
}
.rm-key-item { display: inline-flex; align-items: center; gap: 10px; font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase; color: var(--muted); }
.rm-glyph { width: 12px; height: 12px; flex: none; overflow: visible; }
.rm-glyph-ring { fill: none; stroke: var(--accent); stroke-width: 1.2; }
.rm-glyph-core { fill: var(--accent); }
.rm-glyph--live .rm-glyph-ring { fill: var(--accent); }
.rm-glyph--live { filter: drop-shadow(0 0 5px rgba(var(--nc-primary-rgb), 0.85)); }
.rm-glyph--designed .rm-glyph-ring { stroke: rgba(var(--nc-primary-rgb), 0.8); }
.rm-glyph--planned .rm-glyph-ring { stroke: var(--accent); stroke-width: 1.4; stroke-dasharray: 2 1.8; }
.rm-glyph--idea .rm-glyph-ring { stroke: rgba(var(--nc-primary-rgb), 0.7); stroke-dasharray: 0.4 2.1; stroke-linecap: round; }
.rm-track { list-style: none; margin: 0; padding: 0; }
.rm-horizon { display: grid; grid-template-columns: 120px minmax(0, 1fr); border-bottom: 1px solid var(--line); }
.rm-horizon-label { padding-top: 36px; font-family: var(--mono); font-size: 11px; font-weight: 600; letter-spacing: 0.28em; color: var(--ink); }
.rm-streams { list-style: none; margin: 0; padding: 0; position: relative; }
.rm-streams::before { content: ''; position: absolute; left: 5.5px; top: 0; bottom: 0; width: 1px; background: var(--line-strong); }
.rm-stream { position: relative; padding: 32px 0 34px 42px; }
.rm-stream + .rm-stream { border-top: 1px dashed var(--line); }
.rm-stream-node { position: absolute; left: 0; top: 39px; background: var(--bg); box-shadow: 0 0 0 5px var(--bg); border-radius: 50%; }
.rm-stream-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px 20px; flex-wrap: wrap; }
.rm-stream-head .rm-h3 { font-size: 1.32rem; font-weight: 400; }
.rm-stream-status { font-family: var(--mono); font-size: 10px; font-weight: 500; letter-spacing: 0.22em; text-transform: uppercase; color: var(--accent); }
.rm-items { list-style: none; margin: 18px 0 0; padding: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 32px; }
.rm-item { position: relative; padding-left: 20px; font-size: 0.93rem; line-height: 1.55; color: #c2ced7; }
.rm-item::before { content: ''; position: absolute; left: 0; top: 11px; width: 9px; height: 0; border-top: 1px solid var(--accent); }
.rm-stream-link { margin-top: 24px; }

/* 03 whitepapers */
.rm-papers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.rm-paper {
  position: relative; display: flex; flex-direction: column; min-height: 320px; padding: 30px 32px 30px;
  text-decoration: none; color: var(--text);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.05), rgba(var(--nc-primary-rgb), 0.008) 70%);
  border: 1px solid var(--line);
  transition: border-color 0.25s, transform 0.25s;
}
.rm-paper::before { content: ''; position: absolute; left: -1px; right: -1px; top: -1px; height: 2px; background: rgba(var(--nc-primary-rgb), 0.4); }
.rm-paper--new::before { background: var(--warm); }
.rm-paper:hover, .rm-paper:focus-visible { border-color: var(--line-strong); transform: translateY(-2px); outline: none; }
.rm-paper-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.rm-paper-tag { font-family: var(--mono); font-size: 10px; font-weight: 500; letter-spacing: 0.22em; color: var(--muted); padding-top: 4px; }
.rm-paper-tag--new { color: var(--warm); }
.rm-paper-glyph { width: 26px; height: 32px; flex: none; overflow: visible; }
.rm-paper-title { font-family: var(--sans); font-size: 1.7rem; font-weight: 300; line-height: 1.2; letter-spacing: -0.018em; color: var(--ink); margin: 64px 0 16px; }
.rm-paper-link { margin-top: auto; align-self: flex-start; }
.rm-paper .rm-p { margin-bottom: 26px; }

/* 04 reference pages */
.rm-surfaces { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.rm-surface {
  display: flex; flex-direction: column; padding: 30px 32px; text-decoration: none; color: var(--text);
  border: 1px solid var(--line); transition: border-color 0.25s, background 0.25s;
}
.rm-surface:hover, .rm-surface:focus-visible { border-color: var(--line-strong); background: rgba(var(--nc-primary-rgb), 0.025); outline: none; }
.rm-surface-path { font-family: var(--mono); font-size: 12px; font-weight: 500; letter-spacing: 0.04em; color: var(--accent); margin-bottom: 22px; }
.rm-dl { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 12px 18px; margin: 10px 0 26px; }
.rm-dt { font-family: var(--mono); font-size: 10px; font-weight: 500; line-height: 2.1; letter-spacing: 0.22em; text-transform: uppercase; color: var(--muted); }
.rm-dt--next { color: var(--accent); }
.rm-dd { margin: 0; font-size: 0.95rem; line-height: 1.68; color: var(--text); }
.rm-surface .rm-link { margin-top: auto; align-self: flex-start; }

/* 05 the note */
.rm-letter { margin: 0; max-width: 44em; }
.rm-letter .rm-h2 { margin-bottom: 36px; }
.rm-letter-body { margin: 0; padding: 0; }
.rm-letter-p { font-size: 1.2rem; font-weight: 300; line-height: 1.85; color: #d2dce3; margin: 0 0 22px; }
.rm-sign { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 18px; margin-top: 40px; }
.rm-sign::before { content: ''; width: 56px; height: 1px; background: var(--accent); }
.rm-sign-name { font-size: 1rem; font-weight: 400; color: var(--ink); }
.rm-sign-role { font-family: var(--mono); font-size: 10px; font-weight: 500; letter-spacing: 0.24em; text-transform: uppercase; color: var(--muted); }

/* 06 lines we hold */
.rm-lines { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 56px; }
.rm-line { display: grid; grid-template-columns: 48px minmax(0, 1fr); padding: 28px 0 30px; border-top: 1px solid var(--line); }
.rm-line-index { font-family: var(--mono); font-size: 11px; font-weight: 500; line-height: 2.3; letter-spacing: 0.16em; color: var(--accent); }
.rm-line-text { font-size: 1.3rem; font-weight: 300; line-height: 1.45; letter-spacing: -0.01em; color: var(--ink); }

/* footer */
.rm-footer { position: relative; z-index: 1; border-top: 1px solid var(--line); }
.rm-footer-inner {
  max-width: 1200px; margin: 0 auto; padding: 34px 40px 72px;
  display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 18px 40px;
}
.rm-footer-mark { font-family: var(--mono); font-size: 10.5px; font-weight: 500; letter-spacing: 0.24em; text-transform: uppercase; color: var(--muted); }
.rm-footer-links { display: flex; flex-wrap: wrap; gap: 12px 26px; }
.rm-footer-links a {
  font-family: var(--mono); font-size: 10.5px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--text); text-decoration: none;
  transition: color 0.2s;
}
.rm-footer-links a:hover, .rm-footer-links a:focus-visible { color: var(--accent); outline: none; }

/* reveal */
.rm-reveal { opacity: 0; transform: translateY(14px); transition: opacity 0.8s ease, transform 0.8s cubic-bezier(0.2, 0.7, 0.2, 1); }
.rm-reveal.rm-in { opacity: 1; transform: none; }

/* ── responsive ──────────────────────────────────────────────────────── */
@media (max-width: 1080px) {
  .rm-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rm-control:nth-child(3) { padding-left: 0; border-left: 0; }
  .rm-control:nth-child(n + 3) { border-top: 1px solid var(--line); }
}
@media (max-width: 980px) {
  .rm-hero { grid-template-columns: minmax(0, 1fr); padding-top: 80px; gap: 56px; }
  .rm-reactor { max-width: 420px; }
  .rm-section { grid-template-columns: minmax(0, 1fr); gap: 32px; padding: 72px 0; }
  .rm-rail { position: static; flex-direction: row; align-items: baseline; gap: 18px; }
  .rm-rail-index { font-size: 2rem; }
}
@media (max-width: 680px) {
  .rm-chrome-inner, .rm-hero, .rm-footer-inner { padding-left: 16px; padding-right: 16px; }
  .rm-main { padding: 0 16px; }
  .rm-chrome-mark { display: none; }
  .rm-hero { padding-top: 56px; padding-bottom: 72px; gap: 44px; }
  .rm-reactor { max-width: 330px; }
  .rm-section { padding: 60px 0; }
  .rm-h2 { margin-bottom: 36px; }
  .rm-controls { grid-template-columns: minmax(0, 1fr); }
  .rm-control, .rm-control + .rm-control { padding: 26px 0 8px; border-left: 0; }
  .rm-control .rm-h3 { min-height: 0; }
  .rm-control + .rm-control { border-top: 1px solid var(--line); }
  .rm-horizon { grid-template-columns: minmax(0, 1fr); }
  .rm-horizon-label { padding-top: 28px; }
  .rm-stream { padding: 22px 0 26px 34px; }
  .rm-stream-node { top: 29px; }
  .rm-items, .rm-papers, .rm-surfaces, .rm-lines { grid-template-columns: minmax(0, 1fr); }
  .rm-paper { min-height: 0; padding: 26px 24px; }
  .rm-paper-title { margin-top: 40px; font-size: 1.5rem; }
  .rm-surface { padding: 26px 24px; }
  .rm-letter-p { font-size: 1.1rem; }
  .rm-line-text { font-size: 1.16rem; }
}
@media (prefers-reduced-motion: reduce) {
  .rm-scan, .rm-ring-dash, .rm-core-glow, .rm-rod, .rm-chrome-dot { animation: none; }
  .rm-reveal { opacity: 1; transform: none; transition: none; }
}
/* Paper gets the page the screen shows, its dark ground, colours and hairlines included, whatever
   the print dialog's background setting: like the journal and the compliance pages. Only the
   navigation bar and the scan line stay off paper. The hero is the cover, the reactor under its
   words; each section opens a page, so no heading is left at the foot of one, and no card or
   stream breaks across two. */
@media print {
  .rm-page { -webkit-print-color-adjust: exact; print-color-adjust: exact; min-height: 0; overflow: visible; }
  .rm-chrome, .rm-scan { display: none; }
  .rm-rail { position: static; }
  .rm-reveal { opacity: 1; transform: none; transition: none; }
  .rm-ring-dash, .rm-core-glow, .rm-rod, .rm-chrome-dot { animation: none; }
  .rm-hero { gap: 40px; padding-top: 56px; padding-bottom: 40px; }
  .rm-reactor { max-width: 380px; margin: 0 auto; }
  .rm-section { break-before: page; border-top: 0; padding: 24px 0 0; }
  .rm-rail, .rm-h2, .rm-intro { break-after: avoid; }
  .rm-control, .rm-key, .rm-stream, .rm-paper, .rm-surface, .rm-letter, .rm-line { break-inside: avoid; }
}
</style>
