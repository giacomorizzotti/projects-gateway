<script setup>
// Label + input (default slot) + its validation error or a hint.
defineProps({
  label: { type: String, default: '' },
  id: { type: String, default: '' },
  error: { type: String, default: '' },
  help: { type: String, default: '' },
})
</script>

<template>
  <div class="form-field mb-1">
    <label v-if="label" :for="id || undefined" class="S">{{ label }}</label>
    <slot/>
    <p v-if="error" class="danger-text XS m-0" role="alert">{{ error }}</p>
    <p v-else-if="help" class="muted-text XS m-0">{{ help }}</p>
  </div>
</template>
