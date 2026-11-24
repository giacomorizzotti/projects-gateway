<script setup>
// A coloured dot for the checks of one environment (or one URL): green up, red down,
// amber for a certificate close to expiry or a name pointing away from its platform,
// grey when not checked. The words are in the label, for screen readers and the tooltip.
import { computed } from 'vue'
import { checkSummary } from '@/utils/status'

const props = defineProps({
  checks: { type: Array, default: () => [] },
})

const summary = computed(() => checkSummary(props.checks))
</script>

<template>
  <span class="status-dot" :class="summary.cls" role="img" :aria-label="summary.label" :title="summary.title"></span>
</template>

<style scoped>
.status-dot {
  display: inline-block;
  flex: none;
  width: .6em;
  height: .6em;
  border-radius: 50%;
  vertical-align: .05em;
}
</style>
