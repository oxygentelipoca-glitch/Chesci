<script setup>
import { statusLabel } from '../utils/routeEvidence.js'
defineProps({ checks: { type: Array, required: true } })
</script>

<template>
  <ul class="checks" aria-label="实验室条件核对">
    <li v-for="check in checks" :key="check.key">
      <span class="status" :class="check.status">{{ statusLabel[check.status] }}</span>
      <span>{{ check.requirement }}<small>记录：{{ check.record }}</small></span>
    </li>
  </ul>
</template>

<style scoped>
.checks { display: grid; gap: 5px; margin: 6px 0; padding: 0; list-style: none; }
li { display: flex; gap: 6px; align-items: baseline; font-size: 13px; overflow-wrap: anywhere; }
.status { flex-shrink: 0; padding: 1px 5px; border-radius: 4px; font-size: 12px; }
.met { color: #065f46; background: #d1fae5; }
.conflict { color: #9f1239; background: #ffe4e6; }
.unknown { color: #713f12; background: #fef3c7; }
small { display: block; color: var(--text-light); white-space: pre-line; }
</style>
