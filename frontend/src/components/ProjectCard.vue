<script setup>
// One project as a card: name, status, client and description, then its environments.
// The dashboard shows them all; a platform page passes only the ones running on it
// (and hides the platform on each line: it's the page's own). Its repositories,
// technologies and services are under "Details", closed by default.
import { computed } from 'vue'
import { Cloud, CubeScan, Folder, Repository } from '@iconoir/vue'
import Collapsible from '@/mini/components/Collapsible.vue'
import Space from '@/mini/components/Space.vue'
import EnvironmentLine from '@/components/EnvironmentLine.vue'
import { useCatalogStore } from '@/stores/catalog'
import { envBorderColor, envColor, statusClass } from '@/utils/format'

const props = defineProps({
  project: { type: Object, required: true },
  environments: { type: Array, default: null },      // default: all of the project's
  showPlatform: { type: Boolean, default: true },
})

const envs = computed(() => props.environments ?? props.project.environments)

const catalog = useCatalogStore()
const repos = computed(() => props.project.repositories || [])
const techs = computed(() => props.project.technology_names || [])
const services = computed(() => {
  const ids = new Set(props.project.service_ids || [])
  return catalog.services.filter(s => ids.has(s.id))
})
const hasDetails = computed(() => repos.value.length || techs.value.length || services.value.length)
// On the closed button, so the repos show without opening it.
const detailsLabel = computed(() =>
  'Details' + (repos.value.length ? `  ·  ${repos.value.length} repo${repos.value.length === 1 ? '' : 's'}` : ''))
</script>

<template>
  <div class="project-card p-15 project-border fb-bg" style="border-top: 3px solid;">
    <div class="flex justify-content-between align-items-start">
      <RouterLink :to="{ name: 'project', params: { slug: project.slug } }">
        <h4 class="m-0">
          <Folder width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 project-text"/>
          {{ project.name }}
          <span v-if="statusClass(project.status)" :class="[statusClass(project.status), 'flag border-0 regular p-05 ms-05']">{{ project.status_label }}</span>
        </h4>
      </RouterLink>
    </div>
    <p class="S light-grey-text m-0" v-if="project.client_name || project.description">
      <strong v-if="project.client_name">{{ project.client_name }}</strong>
      <template v-if="project.client_name && project.description">&nbsp;&nbsp;·&nbsp;&nbsp;</template>{{ project.description }}
    </p>
    <Space/>
    <ul class="env-list S" v-if="envs.length">
      <li v-for="env in envs" :key="env.id" :class="['mt-0 mb-15 p-1 border dark-grey-border']">
        <EnvironmentLine :env="env" :showPlatform="showPlatform"/>
      </li>
    </ul>
    <Collapsible v-if="hasDetails" :openLabel="detailsLabel" closeLabel="Hide details"
                buttonSize="XS" buttonInvert buttonColor="grey" buttonClass="m-0" contentClass="S mt-05">
      <p v-for="r in repos" :key="r.slug" class="mt-0 mb-1 lh-15">
        <Repository width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 repository-text"/><span class="grey-text XS">Repo:</span><br/>
        <a v-if="r.github_url" :href="r.github_url" target="_blank" rel="noopener noreferrer" class="repository-text">{{ r.name }}</a>
        <RouterLink v-else :to="{ name: 'repositories' }" class="repository-text">{{ r.name }}</RouterLink>
        <span v-if="r.language" class="XS muted-text">&nbsp;&nbsp;·&nbsp;&nbsp;{{ r.language }}</span>
        <span v-if="r.archived" class="XS muted-text">&nbsp;&nbsp;·&nbsp;&nbsp;archived</span>
      </p>
      <p v-if="services.length" class="mt-0 mb-1 lh-15">
        <Cloud width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 service-text"/>
        <span class="grey-text XS">Services:</span><br/>
        <span v-for="(s, i) in services" :key="s.id"><template v-if="i">, </template>
          <RouterLink :to="{ name: 'services' }">{{ s.name }}</RouterLink></span>
      </p>
      <p v-if="techs.length" class="m-0 mb-1 lh-15">
        <CubeScan width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 technology-text"/>
        <span class="grey-text XS">Tech:</span><br/>
        <span v-for="t in techs" :key="t" class="technology-box XS mt-05 me-05">{{ t }}</span>
      </p>
      <Space/>
    </Collapsible>
  </div>
</template>

<style lang="scss" module>

</style>
