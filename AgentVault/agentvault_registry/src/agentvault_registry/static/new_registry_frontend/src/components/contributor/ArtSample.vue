<!--
  ArtSample — one piece of artwork in the review gallery, marked as what it is (V0665; session-lead seq 4967, after the console proof's color-contrast finding on /admin/flare-art):
  an image with a name, and everything drawn inside it (the initials of a sample avatar, a sample name, the plate's own lettering) hidden from the checker and from a screen reader,
  so the artwork is read as artwork and the real captions beside it carry the contrast the gallery owes.
-->
<template>
  <div class="art-sample" role="img" :aria-label="label"><span class="art-sample-in" aria-hidden="true"><slot /></span></div>
</template>

<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<style scoped>
.art-sample { display: inline-flex; align-items: center; }
.art-sample-in { display: contents; }
</style>
