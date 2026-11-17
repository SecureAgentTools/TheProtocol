// markdown-it-container ships no types, and there is no @types package for it. Declared once here for the docs
// composable (composables/docs/useDocsMarkdown) and the chat message renderer (services/chat/messageText), which each
// carried a TS7016 for the import (V0662 Wave 1 merge).
declare module 'markdown-it-container' {
  import type { PluginWithParams } from 'markdown-it'
  const container: PluginWithParams
  export default container
}
