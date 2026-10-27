import tailwindcss from '@tailwindcss/postcss'
import tailwindV3Siblings from './postcss/tailwind-v3-siblings.js'

export default {
  // the second plugin keeps v3's space-x/y and divide-x/y (postcss/tailwind-v3-siblings.js says why)
  plugins: [tailwindcss(), tailwindV3Siblings()],
}
