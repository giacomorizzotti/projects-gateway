<script setup>
// What needs attention, from the Status page: red if anything is, amber otherwise. App.vue
// shows it above every page but the Status page itself, and loads and refreshes the store;
// problems = "needs attention" minus the info-only items.
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { useStatusStore } from '@/stores/status'

const status = useStatusStore()
const problemsBox = computed(() =>
  status.problems.some(i => i.severity === 'danger') ? 'danger-box' : 'warning-box')
</script>

<template>
  <p v-if="status.problems.length" class="m-0">
    <span :class="[problemsBox, 'p-1']">
      <RouterLink :to="{ name: 'status' }">
        {{ status.problems.length === 1 ? '1 problem needs' : `${status.problems.length} problems need` }} attention
      </RouterLink>:
      {{ status.problems.slice(0, 3).map(i => i.title).join('&nbsp;&nbsp;·&nbsp;&nbsp;') }}<template v-if="status.problems.length > 3"> …</template>
    </span>
  </p>
</template>
