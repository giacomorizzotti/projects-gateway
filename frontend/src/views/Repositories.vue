<script setup>
import { computed, onMounted, ref } from 'vue'
import { Folder, Repository } from '@iconoir/vue'
import Container from '@/mini/components/Container.vue'
import Boxes from '@/mini/components/Boxes.vue'
import Box from '@/mini/components/Box.vue'
import Space from '@/mini/components/Space.vue'
import LoadingBox from '@/mini/components/LoadingBox.vue'
import Button from '@/mini/components/Button.vue'
import EditButton from '@/components/EditButton.vue'
import GitHubCard from '@/components/GitHubCard.vue'
import RepositoryForm from '@/components/forms/RepositoryForm.vue'
import { usePersistedRef } from '@/mini/composables/usePersistedRef'
import { useCatalogStore } from '@/stores/catalog'
import CatalogCounts from '@/components/CatalogCounts.vue'
import { formatDate, needsAttention, needsProject } from '@/utils/format'

const catalog = useCatalogStore()
onMounted(() => catalog.load())

const search = usePersistedRef('gateway.repos.search', '')
const hosting = usePersistedRef('gateway.repos.hosting', '')
const attentionOnly = usePersistedRef('gateway.repos.attentionOnly', false)

// Everything a search can match: the repo, where it lives, and the projects using it.
function haystack(r) {
  return [
    r.name, r.slug, r.github_description, r.language, r.hosting_label, r.notes,
    r.github_url, r.remote_url, r.local_path, ...(r.topics || []),
    ...r.project_details.map(p => p.name),
  ].filter(Boolean).join(' ').toLowerCase()
}

const repos = computed(() => {
  const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean)
  return catalog.repositories.filter(r =>
    (!hosting.value || r.hosting === hosting.value) && (!attentionOnly.value || needsAttention(r))
    && (!terms.length || terms.every(t => haystack(r).includes(t))))
})

function clearFilters() {
  search.value = ''
  hosting.value = ''
  attentionOnly.value = false
}

function showAttention() {
  hosting.value = ''
  attentionOnly.value = true
}

const hostings = computed(() => catalog.choices?.repository_hostings || [])

// The repository being edited: null = closed, {} = a new one.
const editing = ref(null)
</script>

<template>
  <Container>
    <Boxes spaceTop class="align-items-end">
      <Box :size="75">
        <h1 class="m-0">Repositories</h1>
        <p class="light-grey-text m-0">Git repos on GitHub, Bitbucket, hosting deploy remotes, and local-only ones.</p>
        <CatalogCounts class="mt-05 mb-1"/>
        <Space/>
        <p class="m-0">
          <Button :disabled="!catalog.choices" @click="editing = {}" size="S" class="repository-btn" hard>+ New repository</Button>
        </p>
      </Box>
      <Box :size="100">
        <GitHubCard @showAttention="showAttention"/>
      </Box>
      <Box :size="33">
        <label for="repo-search" class="S">Search</label>
        <input id="repo-search" type="search" v-model.trim="search" class="w-100"
               placeholder="Name, project, language, path…">
      </Box>
      <Box :size="33">
        <label for="hosting" class="S">Hosting</label>
        <select id="hosting" v-model="hosting" class="w-100">
          <option value="">All</option>
          <option v-for="h in hostings" :key="h.value" :value="h.value">{{ h.label }}</option>
        </select>
      </Box>
      <Box :size="33" class="flex align-items-center">
        <label class="S chip"><input type="checkbox" v-model="attentionOnly"> Only the ones that need attention</label>
        <span class="S muted-text ms-1">{{ repos.length }} of {{ catalog.repositories.length }}</span>
      </Box>
    </Boxes>
    <Space height="2"/>
    <!-- A card per repository, in the dashboard's style and the repositories' fourth colour. -->
    <Boxes class="mb-2" gap="2">
      <Box :size="100" v-if="catalog.loading && !catalog.choices"><LoadingBox/></Box>
      <Box :size="100" v-else-if="catalog.error"><p class="danger-box">{{ catalog.error }}</p></Box>
      <Box :size="100" v-else-if="!repos.length">
        <p class="muted-text">No repository matches&nbsp;&nbsp;·&nbsp;&nbsp;<a href="#" @click.prevent="clearFilters">clear filters</a></p>
      </Box>
      <Box v-for="r in repos" :key="r.slug" :size="33" padding="0">
        <div class="repository-card p-15 repository-border wrap-anywhere fb-bg" style="border-top: 3px solid;">
          <div class="flex justify-content-between align-items-start g-0 mb-1">
            <h4 class="m-0 repository-text">
              <Repository width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="repository-text me-05"/>{{ r.name }}
            </h4>
            <EditButton :label="`Edit ${r.name}`" @click="editing = r" class="ms-05"/>
          </div>
          <p class="mt-0 mb-1 flex flex-wrap g-0 XS">
            <span class="repository-box border-0 b-rad-3 p-05 white-text me-05 mb-05">{{ r.hosting_label }}</span>
            <span v-if="!r.private" class="dark-grey-box border info-border b-rad-3 p-05 me-05 mb-05">public</span>
            <span v-if="r.archived" class="grey-box border light-grey-border b-rad-3 p-05 me-05 mb-05">archived</span>
            <span v-if="r.fork" class="dark-grey-box border info-border b-rad-3 p-05 me-05 mb-05">fork</span>
            <span v-if="needsProject(r)" class="dark-grey-box border warning-border b-rad-3 p-05 me-05 mb-05">no project</span>
            <span v-if="r.github_missing" class="flag danger-bg border-0 b-rad-3 p-05 me-05 mb-05">not found on GitHub</span>
          </p>
          <p v-if="r.github_description" class="S m-0">{{ r.github_description }}</p>
          <p v-if="r.language || r.pushed_at" class="muted-text XS m-0">
            {{ r.language }}<template v-if="r.pushed_at"><template v-if="r.language">&nbsp;&nbsp;·&nbsp;&nbsp;</template>pushed {{ formatDate(r.pushed_at) }}</template>
          </p>
          <div class="S mt-05">
            <div v-if="r.github_url"><a :href="r.github_url" target="_blank" rel="noopener noreferrer" class="repository-text">{{ r.github_url.replace(/^https:\/\//, '') }}</a></div>
            <div v-else-if="r.remote_url"><code class="XS py-025 px-05">{{ r.remote_url }}</code></div>
            <div v-if="r.local_path" class="mt-025"><code class="XS py-025 px-05">{{ r.local_path }}</code></div>
          </div>
          <ul v-if="r.project_details.length" class="env-list S">
            <li v-for="p in r.project_details" :key="p.slug">
              <RouterLink :to="{ name: 'project', params: { slug: p.slug } }">
                <Folder width="0.9em" height="0.9em" aria-hidden="true" style="vertical-align: -0.1em" class="me-05 project-text"/>{{ p.name }}
              </RouterLink>
            </li>
          </ul>
        </div>
      </Box>
    </Boxes>

    <RepositoryForm :visible="!!editing" :repository="editing?.id ? editing : null"
                    @close="editing = null" @saved="editing = null"/>
  </Container>
</template>
