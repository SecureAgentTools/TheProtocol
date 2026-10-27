import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

/**
 * Project-canonical viewport breakpoints. Mobile pass 2026-05-08.
 * Mirrors Tailwind defaults so utility classes stay consistent.
 *
 *   sm: 640   — phone (most aggressive layout switch lives here)
 *   md: 768   — large phone / small tablet
 *   lg: 1024  — sidebar fold; mobile drawer ends here, desktop fixed sidebar begins
 *   xl: 1280  — comfortable desktop (no mobile-specific changes above this)
 */
export const BP = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
} as const

let _instance: ReturnType<typeof create> | null = null

function create() {
  // SSR-safe defaults (1280 lands us in desktop layout for any tooling that
  // hits the composable before window is real).
  const width = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
  const height = ref(typeof window !== 'undefined' ? window.innerHeight : 800)

  const isMobile = computed(() => width.value < BP.lg)        // <1024 → drawer + stacked layouts
  const isPhone = computed(() => width.value < BP.md)         // <768  → most aggressive collapse
  const isSmallPhone = computed(() => width.value < BP.sm)    // <640  → sheet modals, single-col grids
  const isTablet = computed(() => width.value >= BP.md && width.value < BP.lg)
  const isDesktop = computed(() => width.value >= BP.lg)

  // Touch detection — used to bias UI choices (e.g. close-on-route-change for
  // drawers, full-screen palette). Coarse pointer = primarily touch, no hover.
  const hasTouch = ref(false)
  const hasHover = ref(true)

  function refresh() {
    if (typeof window === 'undefined') return
    width.value = window.innerWidth
    height.value = window.innerHeight
  }

  function refreshPointer() {
    if (typeof window === 'undefined' || !window.matchMedia) return
    hasTouch.value = window.matchMedia('(pointer: coarse)').matches
    hasHover.value = window.matchMedia('(hover: hover)').matches
  }

  // Module-level listeners — installed once across all consumers so
  // many components don't each pay for a resize handler.
  let mounted = 0
  let resizeBound = false
  let mqlPointer: MediaQueryList | null = null
  let mqlHover: MediaQueryList | null = null
  const onResize = () => refresh()
  const onPointerChange = () => refreshPointer()

  function mount() {
    if (typeof window === 'undefined') return
    mounted++
    if (mounted === 1 && !resizeBound) {
      window.addEventListener('resize', onResize, { passive: true })
      window.addEventListener('orientationchange', onResize, { passive: true })
      resizeBound = true
      mqlPointer = window.matchMedia('(pointer: coarse)')
      mqlHover = window.matchMedia('(hover: hover)')
      // Modern browsers: addEventListener('change'). Older Safari needs addListener.
      mqlPointer.addEventListener?.('change', onPointerChange)
      mqlHover.addEventListener?.('change', onPointerChange)
      refresh()
      refreshPointer()
    }
  }
  function unmount() {
    mounted = Math.max(0, mounted - 1)
    if (mounted === 0 && resizeBound) {
      window.removeEventListener('resize', onResize)
      window.removeEventListener('orientationchange', onResize)
      mqlPointer?.removeEventListener?.('change', onPointerChange)
      mqlHover?.removeEventListener?.('change', onPointerChange)
      mqlPointer = null
      mqlHover = null
      resizeBound = false
    }
  }

  return { width, height, isMobile, isPhone, isSmallPhone, isTablet, isDesktop, hasTouch, hasHover, mount, unmount, refresh }
}

/**
 * Reactive viewport — single shared instance. Components subscribe via
 * `const vp = useViewport()` then read `vp.isMobile.value` etc.
 *
 * Read at top-level setup so the lifecycle hooks fire correctly. Don't
 * call inside async post-await (mirrors useRoute() rule).
 */
export function useViewport() {
  if (!_instance) _instance = create()
  const i = _instance
  onMounted(() => i.mount())
  onBeforeUnmount(() => i.unmount())
  return i
}
