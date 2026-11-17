<script setup>
defineProps({ links: { type: Array, required: true } })
</script>

<template>
  <div v-if="links.length" class="paper-links">
    <a v-for="link in links" :key="link.url" :href="link.url" target="_blank" rel="noopener noreferrer" @click.stop>{{ link.label }}</a>
  </div>
</template>

<style scoped>
.paper-links { display: grid; gap: .25rem; margin-block: .3rem; font-size: .8rem; }
a { color: var(--primary); overflow-wrap: anywhere; }
</style>
