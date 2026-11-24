<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import Button from '@/mini/components/Button.vue'
import Tabs from '@/mini/components/Tabs.vue'
import { usePersistedRef } from '@/mini/composables/usePersistedRef'
import { useDashboardFilters } from '@/composables/useDashboardFilters'
import ProjectCard from '@/components/ProjectCard.vue'
import ProjectTree from '@/components/ProjectTree.vue'
import ProjectForm from '@/components/forms/ProjectForm.vue'
import { useCatalogStore } from '@/stores/catalog'
import CatalogCounts from '@/components/CatalogCounts.vue'
import { byClient, byDependency, byGroup, byPlatform } from '@/utils/trees'

const catalog = useCatalogStore()
const router = useRouter()
onMounted(() => catalog.load())

const creating = ref(false)
function onCreated(project) {
  creating.value = false
  router.push({ name: 'project', params: { slug: project.slug } })
}

// Shared with the header's logo, which resets them.
const { search, platform, showArchived } = useDashboardFilters()
const VIEWS = [{ value: 'cards', label: 'Cards' }, { value: 'tree', label: 'Tree' }]
const view = usePersistedRef('gateway.dashboard.view', 'cards')            // cards | tree
const TREE_BY = ['dependency', 'platform', 'group', 'client']
const treeBy = usePersistedRef('gateway.dashboard.treeBy', 'dependency')   // one of TREE_BY

const HIDDEN_STATUSES = ['archived', 'discontinued']
// Groups set as hidden on the Settings page (Archive), shown only with "Show archived".
const hiddenGroups = computed(() =>
  new Set((catalog.choices?.project_groups || []).filter(g => g.hidden).map(g => g.value)))

// Everything a search can match: names, client, tech, URLs, paths, platforms, repos.
function haystack(p) {
  return [
    p.name, p.slug, p.description, p.client_name, p.group_label, p.status_label,
    ...p.technology_names,
    ...p.repositories.map(r => r.name),
    ...p.environments.flatMap(e => [e.name, e.path, e.platform_detail?.name, ...e.urls]),
  ].filter(Boolean).join(' ').toLowerCase()
}

const filtered = computed(() => {
  const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean)
  return catalog.projects.filter(p => {
    if (!showArchived.value && (hiddenGroups.value.has(p.group) || HIDDEN_STATUSES.includes(p.status))) return false
    if (platform.value && !p.environments.some(e => e.platform_detail?.slug === platform.value)) return false
    if (!terms.length) return true
    const text = haystack(p)
    return terms.every(t => text.includes(t))
  })
})

const groups = computed(() =>
  (catalog.choices?.project_groups || [])
    .map(g => ({ ...g, projects: filtered.value.filter(p => p.group === g.value) }))
    .filter(g => g.projects.length),
)

// The tree of the same filtered projects, and how many have no dependency to draw.
const treeData = computed(() => {
  if (view.value !== 'tree' || !catalog.choices) return null
  if (treeBy.value === 'platform') return { root: byPlatform(filtered.value, catalog.platforms), untouched: 0 }
  if (treeBy.value === 'group') return { root: byGroup(filtered.value, catalog.choices.project_groups), untouched: 0 }
  if (treeBy.value === 'client') return { root: byClient(filtered.value, catalog.clients), untouched: 0 }
  return byDependency(filtered.value, catalog.dependencies, catalog.projects)
})

const hiddenCount = computed(() => catalog.projects.length - filtered.value.length)

function clearFilters() {
  search.value = ''
  platform.value = ''
}
</script>

<template>
  <Container>
    <Boxes spaceTop class="">
      <Box :size="100">
        <h1 class="mb-0">Projects</h1>
        <CatalogCounts class="mt-05 mb-15"/>
        <p class="m-0">
          <Button :disabled="!catalog.choices" @click="creating = true" size="S" class="project-btn m-0" hard>+ New project</Button>
        </p>
      </Box>
    </Boxes>

    <Boxes class="align-items-end filters py-2">
      <Box :size="33" class="py-0">
        <input id="search" type="search" v-model.trim="search"
               placeholder="Name, client, URL, tech, platform…" class="w-100">
      </Box>
      <Box :size="33" class="py-0">
        <select id="platform" v-model="platform" class="w-100">
          <option value="">All platforms</option>
          <option v-for="pl in catalog.platforms" :key="pl.slug" :value="pl.slug">{{ pl.name }}</option>
        </select>
      </Box>
      <Box :size="33" class="py-0 flex flex-wrap align-items-center">
        <label class="S chip"><input type="checkbox" v-model="showArchived"> Show archived and discontinued</label>
        <p class="S muted-text m-0" v-if="hiddenCount && (search || platform)">
          {{ hiddenCount }} not shown&nbsp;&nbsp;·&nbsp;&nbsp;<a href="#" @click.prevent="clearFilters">clear filters</a>
        </p>
      </Box>
    </Boxes>

    <!-- mx-1: the same inset as the filter boxes above -->
    <Tabs v-model="view" :tabs="VIEWS" label="View" class="m-1">
      <LoadingBox dark v-if="catalog.loading && !catalog.choices"/>
      <p v-else-if="catalog.error" class="danger-box mx-1">{{ catalog.error }}</p>
      <p v-else-if="!groups.length" class="muted-text mx-1">No project matches.</p>

      <div v-else-if="view === 'tree' && treeData" class="mx-1">
        <div class="flex flex-wrap gap-05 align-items-center S mb-1" role="radiogroup" aria-labelledby="tree-by">
          <span id="tree-by" class="muted-text me-05">Tree by</span>
          <label v-for="by in TREE_BY" :key="by" class="chip XS">
            <input type="radio" name="tree-by" :value="by" v-model="treeBy"> {{ by }}
          </label>
        </div>
        <p v-if="treeBy === 'dependency'" class="S muted-text">
          Who uses what, and how. Live: gets changes at once&nbsp;&nbsp;·&nbsp;&nbsp;manual: only by a pull, deploy or new copy&nbsp;&nbsp;·&nbsp;&nbsp;pinned: stays on its version.
          <template v-if="treeData.untouched">{{ treeData.untouched }} of the projects shown don’t depend on anything recorded, so they’re not here.</template>
        </p>
        <p v-if="!treeData.root.children.length" class="muted-text">Nothing to draw with these filters.</p>
        <ProjectTree v-else :root="treeData.root" class="mb-2"/>
      </div>

      <section v-for="group in (view === 'cards' ? groups : [])" :key="group.value" class="mb-1 p-1">
        <Boxes class="align-items-start" gap="2">
          <Box :size="100" class="">
            <div class="">
              <h3 class="p light m-0 grey-text">{{ group.label }} <span class="flag S project-text border-0">{{ group.projects.length }}</span></h3>
            </div>
          </Box>
          <Box v-for="p in group.projects" :key="p.slug" :size="33" padding="0">
            <ProjectCard :project="p"/>
          </Box>
        </Boxes>
      </section>
    </Tabs>

    <ProjectForm :visible="creating" @close="creating = false" @saved="onCreated"/>
  </Container>
</template>
