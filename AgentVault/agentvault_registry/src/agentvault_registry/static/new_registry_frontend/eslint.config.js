// ESLint 10 flat config (§DEPS FE step 3, 2026-09-28): the rules of the .eslintrc.cjs it replaces, over the same files.
// - scope: every JS/TS/Vue file here except what .gitignore names (dist/, TempScreenshots/) and node_modules, which is
//   what `eslint . --ext ... --ignore-path .gitignore` linted, minus the vendored bundles (below);
// - browser globals are stated here: eslint-plugin-vue 9's base set `env: { browser: true }` for the old config, and
//   version 10's flat base sets none (every browser global would otherwise read as no-undef);
// - @rushstack/eslint-patch is gone: flat config resolves plugins by import, which is what the patch emulated.
import js from '@eslint/js'
import globals from 'globals'
import pluginVue from 'eslint-plugin-vue'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import skipFormatting from '@vue/eslint-config-prettier/skip-formatting'

const production = process.env.NODE_ENV === 'production'

export default defineConfigWithVueTs(
  // public/vendor holds two third-party bundles (redoc, swagger-ui) under their own licences: the old scope linted them
  // (1,194 of ESLint 8's 1,716 errors) and `npm run lint` passes --fix, which could rewrite them. Not ours to lint.
  { name: 'app/ignores', ignores: ['dist/**', 'TempScreenshots/**', 'public/vendor/**'] },
  { name: 'app/files', files: ['**/*.{js,jsx,cjs,mjs,ts,tsx,cts,mts,vue}'] },
  js.configs.recommended,
  pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,
  skipFormatting,
  {
    name: 'app/rules',
    languageOptions: { ecmaVersion: 'latest', globals: { ...globals.browser } },
    rules: {
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'no-console': production ? 'warn' : 'off',
      'no-debugger': production ? 'warn' : 'off'
    }
  }
)
