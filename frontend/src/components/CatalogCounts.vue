<script setup>
// How big the catalog is: "7 projects · 3 platforms · 12 repositories · 9 services · 14 domains", under the
// title of each of those pages. Each count links to its page, except the page you're on.
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useCatalogStore } from '@/stores/catalog'

const catalog = useCatalogStore()
const route = useRoute()

const counts = computed(() => [
  { page: 'dashboard', n: catalog.projects.length, one: 'project', many: 'projects', cls: 'project-text' },
  { page: 'platforms', n: catalog.platforms.length, one: 'platform', many: 'platforms', cls: 'platform-text' },
  { page: 'domains', n: catalog.domains.length, one: 'domain', many: 'domains', cls: 'domain-text' },
  { page: 'repositories', n: catalog.repositories.length, one: 'repository', many: 'repositories', cls: 'repository-text' },
  { page: 'services', n: catalog.services.length, one: 'service', many: 'services', cls: 'service-text' },
].map(c => ({ ...c, label: `${c.n} ${c.n === 1 ? c.one : c.many}` })))
</script>

<template>
  <p class="muted-text" v-if="catalog.choices">
    <template v-for="(c, i) in counts" :key="c.page">
      <template v-if="i">&nbsp;&nbsp;·&nbsp;&nbsp;</template>
      <template v-if="route.name === c.page">{{ c.label }}</template>
      <RouterLink v-else :to="{ name: c.page }" :class="c.cls">{{ c.label }}</RouterLink>
    </template>
  </p>
</template>
