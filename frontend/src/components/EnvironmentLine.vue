<script setup>
// One environment on one line: kind badge, its first URL (or local path), and the platform.
// A status dot before the URL once the worker has checked it (not for checks off).
import { computed } from 'vue'
import { Server } from '@iconoir/vue'
import StatusDot from '@/components/StatusDot.vue'
import { useStatusStore } from '@/stores/status'
import { envClass, hostOf } from '@/utils/format'

const props = defineProps({
  env: { type: Object, required: true },
  showPlatform: { type: Boolean, default: true },
})

const label = computed(() => (props.env.kind === 'other' ? props.env.name : props.env.kind_label))
const firstUrl = computed(() => props.env.urls?.[0] || '')
const extraUrls = computed(() => Math.max((props.env.urls?.length || 0) - 1, 0))
const status = useStatusStore()
const checks = computed(() => status.byEnvironment[props.env.id] || [])
</script>

<template>
  <span class="wrap-anywhere flex g-0 align-items-center">
    <span :class="[envClass(env.kind), 'XS b-rad-5 me-05 mb-025']">{{ label }}</span>
  </span>
  <span class="wrap-anywhere flex g-0 align-items-center">
    <StatusDot v-if="checks.length" :checks="checks" class="me-05"/>
    <a v-if="firstUrl" :href="firstUrl" target="_blank" rel="noopener noreferrer">{{ hostOf(firstUrl) }}</a>
    <span v-else-if="env.path" class="muted-text S">{{ env.path }}</span>
    <span v-if="extraUrls" class="muted-text S"> +{{ extraUrls }}</span>
  </span>
  <span v-if="showPlatform && env.platform_detail" class="platform-bg py-025 px-075 lh-1 mt-075 inline-block b-rad-5">
    <RouterLink :to="{ name: 'platform', params: { slug: env.platform_detail.slug } }" class="S italic white-text ">
      <Server width="14" height="14" aria-hidden="true" style="vertical-align: -2px" class="me-05"/>
      {{ env.platform_detail.name }}
    </RouterLink>
  </span>
</template>
