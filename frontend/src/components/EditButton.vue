<script setup>
// A small pencil next to something editable.
import { EditPencil } from '@iconoir/vue'

defineProps({ label: { type: String, required: true } })
</script>

<template>
  <button type="button" class="warning-btn-invert XS py-025 px-05 m-0 hard" :aria-label="label" :title="label">
    <EditPencil width="14" height="14" aria-hidden="true" style="vertical-align: text-bottom;"/>
  </button>
</template>
  